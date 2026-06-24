"""Equipment inventory endpoints (Phase 12, Section 7 #21) — org-scoped CRUD.

Reads are open to staff for their own organization (admin: any). Writes require a
sub-admin of that organization, or admin. Equipment is owned by exactly one org.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DatabaseDep, StaffUser
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.schemas.auth import AuthenticatedUser
from app.schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate

log = get_logger(__name__)

router = APIRouter(prefix="/equipment", tags=["equipment"])

_COLS = (
    "id, organization_id, name, category, quantity, status::text as status, "
    "serial_number, description, last_serviced_at, created_at, updated_at"
)


def _can_manage_org(user: AuthenticatedUser, org_id: UUID) -> bool:
    """Admin manages any org; a sub-admin manages only their own organization."""
    if user.role == "admin":
        return True
    return user.role == "sub_admin" and user.primary_org_id == org_id


def _can_view_org(user: AuthenticatedUser, org_id: UUID) -> bool:
    """Admin views any org; sub-admin/response_team view only their own organization."""
    if user.role == "admin":
        return True
    return user.role in ("sub_admin", "response_team") and user.primary_org_id == org_id


@router.get("", response_model=list[EquipmentResponse], summary="List equipment")
async def list_equipment(
    user: StaffUser,
    db: DatabaseDep,
    organization_id: Annotated[UUID | None, Query()] = None,
) -> list[EquipmentResponse]:
    """List equipment for an organization (defaults to the caller's; admin sees all)."""
    if organization_id is not None:
        if not _can_view_org(user, organization_id):
            raise ForbiddenError("You may only view your own organization's equipment.")
        rows = await db.fetch(
            f"select {_COLS} from public.equipment where organization_id = $1 order by name",
            organization_id,
        )
    elif user.role == "admin":
        rows = await db.fetch(
            f"select {_COLS} from public.equipment order by organization_id, name"
        )
    elif user.primary_org_id is not None:
        rows = await db.fetch(
            f"select {_COLS} from public.equipment where organization_id = $1 order by name",
            user.primary_org_id,
        )
    else:
        return []
    return [EquipmentResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/{equipment_id}", response_model=EquipmentResponse, summary="Get one equipment item"
)
async def get_equipment(
    equipment_id: UUID, user: StaffUser, db: DatabaseDep
) -> EquipmentResponse:
    """Get a single equipment item (visibility-checked by organization)."""
    row = await db.fetchrow(
        f"select {_COLS} from public.equipment where id = $1", equipment_id
    )
    if row is None:
        raise NotFoundError("Equipment not found.")
    if not _can_view_org(user, row["organization_id"]):
        raise ForbiddenError("This equipment belongs to another organization.")
    return EquipmentResponse.model_validate(dict(row))


@router.post(
    "",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an equipment item",
)
async def create_equipment(
    payload: EquipmentCreate, user: StaffUser, db: DatabaseDep
) -> EquipmentResponse:
    """Add an equipment item to an organization (admin, or that org's sub-admin)."""
    if not _can_manage_org(user, payload.organization_id):
        raise ForbiddenError("You may only add equipment to your own organization.")
    org = await db.fetchval(
        "select 1 from public.organizations where id = $1", payload.organization_id
    )
    if org is None:
        raise NotFoundError("Organization not found.")
    row = await db.fetchrow(
        f"""
        insert into public.equipment
            (organization_id, name, category, quantity, status, serial_number,
             description, last_serviced_at)
        values ($1, $2, $3, $4, $5::public.equipment_status, $6, $7, $8)
        returning {_COLS}
        """,
        payload.organization_id,
        payload.name,
        payload.category,
        payload.quantity,
        payload.status,
        payload.serial_number,
        payload.description,
        payload.last_serviced_at,
    )
    assert row is not None
    log.info(
        "equipment_created",
        equipment_id=str(row["id"]),
        org_id=str(payload.organization_id),
        by=str(user.id),
    )
    return EquipmentResponse.model_validate(dict(row))


@router.patch(
    "/{equipment_id}", response_model=EquipmentResponse, summary="Update an equipment item"
)
async def update_equipment(
    equipment_id: UUID, payload: EquipmentUpdate, user: StaffUser, db: DatabaseDep
) -> EquipmentResponse:
    """Patch an equipment item (admin, or that org's sub-admin)."""
    org_id = await db.fetchval(
        "select organization_id from public.equipment where id = $1", equipment_id
    )
    if org_id is None:
        raise NotFoundError("Equipment not found.")
    if not _can_manage_org(user, org_id):
        raise ForbiddenError("You may only edit your own organization's equipment.")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise BadRequestError("No fields provided to update.")
    set_parts: list[str] = []
    params: list[Any] = [equipment_id]
    for key, value in fields.items():
        params.append(value)
        if key == "status":
            set_parts.append(f"{key} = ${len(params)}::public.equipment_status")
        else:
            set_parts.append(f"{key} = ${len(params)}")
    row = await db.fetchrow(
        f"update public.equipment set {', '.join(set_parts)} where id = $1 returning {_COLS}",
        *params,
    )
    assert row is not None
    log.info("equipment_updated", equipment_id=str(equipment_id), by=str(user.id))
    return EquipmentResponse.model_validate(dict(row))


@router.delete(
    "/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an equipment item",
)
async def delete_equipment(
    equipment_id: UUID, user: StaffUser, db: DatabaseDep
) -> Response:
    """Delete an equipment item (admin, or that org's sub-admin)."""
    org_id = await db.fetchval(
        "select organization_id from public.equipment where id = $1", equipment_id
    )
    if org_id is None:
        raise NotFoundError("Equipment not found.")
    if not _can_manage_org(user, org_id):
        raise ForbiddenError("You may only delete your own organization's equipment.")
    await db.execute("delete from public.equipment where id = $1", equipment_id)
    log.info("equipment_deleted", equipment_id=str(equipment_id), by=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)