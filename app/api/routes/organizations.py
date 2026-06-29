"""Affiliate organization directory endpoints (admin).

Read-only views over public.organizations and their personnel (public.users by
primary_org_id) for the admin web "Affiliate Organizations" directory. Equipment
for an organization is read via the existing /equipment endpoint.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AdminUser, DatabaseDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.organization import OrganizationMember, OrganizationSummary

log = get_logger(__name__)

router = APIRouter(prefix="/organizations", tags=["organizations"])

_ORG_COLS = (
    "o.id, o.name, o.agency_type::text as agency_type, o.description, "
    "o.contact_email, o.contact_phone, o.address, o.is_active, o.created_at, "
    "(select count(*) from public.users u where u.primary_org_id = o.id) "
    "as personnel_count, "
    "(select count(*) from public.equipment e where e.organization_id = o.id) "
    "as equipment_count"
)


@router.get(
    "",
    response_model=list[OrganizationSummary],
    summary="List affiliate organizations (admin)",
)
async def list_organizations(
    admin: AdminUser, db: DatabaseDep
) -> list[OrganizationSummary]:
    """List every affiliate organization with personnel + equipment counts."""
    rows = await db.fetch(f"select {_ORG_COLS} from public.organizations o order by o.name")
    return [OrganizationSummary.model_validate(dict(r)) for r in rows]


@router.get(
    "/{org_id}/personnel",
    response_model=list[OrganizationMember],
    summary="List an organization's personnel (admin)",
)
async def list_org_personnel(
    org_id: UUID, admin: AdminUser, db: DatabaseDep
) -> list[OrganizationMember]:
    """List the users assigned to an organization (its roster)."""
    exists = await db.fetchval("select 1 from public.organizations where id = $1", org_id)
    if exists is None:
        raise NotFoundError("Organization not found.")
    rows = await db.fetch(
        """
        select id, full_name, role::text as role, agency_type::text as agency_type,
               verified_percent, badge::text as badge
        from public.users
        where primary_org_id = $1
        order by
            case role::text
                when 'sub_admin' then 0
                when 'response_team' then 1
                else 2
            end,
            full_name nulls last
        """,
        org_id,
    )
    return [OrganizationMember.model_validate(dict(r)) for r in rows]
