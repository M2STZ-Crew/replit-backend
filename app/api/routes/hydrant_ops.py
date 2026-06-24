"""Hydrant ground-truth override + BFP CSV import (Phase 12, Section 12).

Fire-Volunteer sub-admins set/clear a hydrant's ground-truth status (audited to
audit_logs); the override wins over the BFP-synced status in effective_status.
Admins bulk-sync BFP hydrant status from a CSV. These sit on top of the generic
admin hydrant CRUD in map_layers_admin.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, UploadFile

from app.api.deps import AdminUser, DatabaseDep, StaffUser
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import (
    HydrantGroundTruthRequest,
    HydrantImportResult,
    HydrantResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/map", tags=["map-layers"])

_HYDRANT_COLS = (
    "id, code, latitude, longitude, address, bfp_status::text as bfp_status, "
    "bfp_synced_at, ground_truth_status::text as ground_truth_status, "
    "ground_truth_by, ground_truth_at, ground_truth_notes, "
    "effective_status::text as effective_status, source, is_active, "
    "created_at, updated_at"
)
_VALID_STATUS = {"operational", "non_operational", "under_maintenance", "unknown"}


def _require_fire_vol_subadmin(user: AuthenticatedUser) -> None:
    """Restrict ground-truth overrides to Fire Volunteer sub-admins (Section 12)."""
    if not (user.role == "sub_admin" and user.agency_type == "fire_volunteer"):
        raise ForbiddenError(
            "Only a Fire Volunteer sub-admin may set hydrant ground-truth status."
        )


async def _audit_hydrant(
    db: Database,
    user: AuthenticatedUser,
    hydrant_id: UUID,
    action: str,
    before: str | None,
    after: str | None,
    notes: str | None,
) -> None:
    """Append an audit_logs row for a hydrant ground-truth change (append-only table)."""
    await db.execute(
        """
        insert into public.audit_logs
            (actor_user_id, actor_role, actor_agency, action, entity_type, entity_id,
             before_state, after_state, metadata)
        values ($1, $2::public.user_role, $3::public.agency_type, $4, 'hydrant', $5,
                $6::jsonb, $7::jsonb, $8::jsonb)
        """,
        user.id,
        user.role,
        user.agency_type,
        action,
        hydrant_id,
        json.dumps({"ground_truth_status": before}),
        json.dumps({"ground_truth_status": after}),
        json.dumps({"notes": notes}),
    )


@router.post(
    "/hydrants/{layer_id}/ground-truth",
    response_model=HydrantResponse,
    summary="Set a hydrant's ground-truth status (Fire-Vol sub-admin)",
)
async def set_hydrant_ground_truth(
    layer_id: UUID, payload: HydrantGroundTruthRequest, user: StaffUser, db: DatabaseDep
) -> HydrantResponse:
    """Override the hydrant's effective status with a Fire-Vol ground-truth reading."""
    _require_fire_vol_subadmin(user)
    cur = await db.fetchrow(
        "select ground_truth_status::text as gt from public.hydrants where id = $1", layer_id
    )
    if cur is None:
        raise NotFoundError("Hydrant not found.")
    row = await db.fetchrow(
        f"""
        update public.hydrants
           set ground_truth_status = $2::public.hydrant_status, ground_truth_by = $3,
               ground_truth_at = now(), ground_truth_notes = $4
         where id = $1
        returning {_HYDRANT_COLS}
        """,
        layer_id,
        payload.status,
        user.id,
        payload.notes,
    )
    assert row is not None
    await _audit_hydrant(
        db, user, layer_id, "hydrant.override", cur["gt"], payload.status, payload.notes
    )
    log.info("hydrant_ground_truth_set", layer_id=str(layer_id), by=str(user.id))
    return HydrantResponse.model_validate(dict(row))


@router.delete(
    "/hydrants/{layer_id}/ground-truth",
    response_model=HydrantResponse,
    summary="Clear a hydrant's ground-truth override (Fire-Vol sub-admin)",
)
async def clear_hydrant_ground_truth(
    layer_id: UUID, user: StaffUser, db: DatabaseDep
) -> HydrantResponse:
    """Remove the Fire-Vol override so effective status falls back to BFP status."""
    _require_fire_vol_subadmin(user)
    cur = await db.fetchrow(
        "select ground_truth_status::text as gt from public.hydrants where id = $1", layer_id
    )
    if cur is None:
        raise NotFoundError("Hydrant not found.")
    row = await db.fetchrow(
        f"""
        update public.hydrants
           set ground_truth_status = null, ground_truth_by = null,
               ground_truth_at = null, ground_truth_notes = null
         where id = $1
        returning {_HYDRANT_COLS}
        """,
        layer_id,
    )
    assert row is not None
    await _audit_hydrant(
        db, user, layer_id, "hydrant.override_cleared", cur["gt"], None, None
    )
    log.info("hydrant_ground_truth_cleared", layer_id=str(layer_id), by=str(user.id))
    return HydrantResponse.model_validate(dict(row))


@router.post(
    "/hydrants/import",
    response_model=HydrantImportResult,
    summary="Import/sync BFP hydrants from a CSV (admin)",
)
async def import_hydrants_csv(
    admin: AdminUser,
    db: DatabaseDep,
    file: Annotated[UploadFile, File()],
) -> HydrantImportResult:
    """Bulk-upsert hydrant BFP status from a CSV (columns: code, latitude, longitude,
    address, bfp_status). Existing hydrants are matched by code."""
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadRequestError("CSV must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(text))
    created = 0
    updated = 0
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        try:
            code = (raw.get("code") or "").strip()
            lat = float(raw["latitude"])
            lng = float(raw["longitude"])
        except (KeyError, ValueError, TypeError):
            errors.append(f"row {line_no}: missing/invalid latitude or longitude")
            continue
        status_val = (raw.get("bfp_status") or raw.get("status") or "unknown").strip().lower()
        if status_val not in _VALID_STATUS:
            errors.append(f"row {line_no}: invalid bfp_status '{status_val}'")
            continue
        address = (raw.get("address") or "").strip() or None
        existing = (
            await db.fetchval("select id from public.hydrants where code = $1", code)
            if code
            else None
        )
        if existing is not None:
            await db.execute(
                """
                update public.hydrants
                   set latitude = $2, longitude = $3,
                       address = coalesce($4, address),
                       bfp_status = $5::public.hydrant_status, bfp_synced_at = now(),
                       source = 'bfp_csv'
                 where id = $1
                """,
                existing,
                lat,
                lng,
                address,
                status_val,
            )
            updated += 1
        else:
            await db.execute(
                """
                insert into public.hydrants
                    (code, latitude, longitude, address, bfp_status, bfp_synced_at, source)
                values ($1, $2, $3, $4, $5::public.hydrant_status, now(), 'bfp_csv')
                """,
                code or None,
                lat,
                lng,
                address,
                status_val,
            )
            created += 1

    log.info(
        "hydrants_csv_imported",
        created=created,
        updated=updated,
        errors=len(errors),
        by=str(admin.id),
    )
    return HydrantImportResult(created=created, updated=updated, errors=errors)