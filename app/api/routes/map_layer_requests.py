"""Map-layer update request workflow endpoints (Phase 12, Section 6).

Sub-admins propose create/update/delete changes to map layers or equipment; admins
approve (which applies the change) or reject. proposed_data is jsonb (no codec, so
dumped/loaded explicitly).
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.schemas.map_layer_request import (
    MapLayerRequestCreate,
    MapLayerRequestResponse,
    MapLayerReviewRequest,
)
from app.services.map_layer_apply import apply_map_layer_request

log = get_logger(__name__)

router = APIRouter(prefix="/map-layer-requests", tags=["map-layer-requests"])

_COLS = (
    "id, requested_by, organization_id, layer_type::text as layer_type, "
    "operation::text as operation, target_id, proposed_data, reason, "
    "status::text as status, reviewed_by, reviewed_at, review_notes, applied_at, "
    "created_at, updated_at"
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Normalize a request row: parse the jsonb proposed_data into a dict."""
    data = dict(row)
    pd = data.get("proposed_data")
    data["proposed_data"] = json.loads(pd) if isinstance(pd, str) else (pd or {})
    return data


@router.post(
    "",
    response_model=MapLayerRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a map-layer update request (sub-admin)",
)
async def submit_request(
    payload: MapLayerRequestCreate, user: StaffUser, db: DatabaseDep
) -> MapLayerRequestResponse:
    """Submit a pending map-layer/equipment change request (sub-admin)."""
    if user.role != "sub_admin":
        raise ForbiddenError("Only a sub-admin may submit map-layer update requests.")
    row = await db.fetchrow(
        f"""
        insert into public.map_layer_update_requests
            (requested_by, organization_id, layer_type, operation, target_id,
             proposed_data, reason)
        values ($1, $2, $3::public.map_layer_type, $4::public.map_layer_operation,
                $5, $6::jsonb, $7)
        returning {_COLS}
        """,
        user.id,
        user.primary_org_id,
        payload.layer_type,
        payload.operation,
        payload.target_id,
        json.dumps(payload.proposed_data),
        payload.reason,
    )
    assert row is not None
    log.info("map_layer_request_submitted", request_id=str(row["id"]), by=str(user.id))
    return MapLayerRequestResponse.model_validate(_row_to_dict(row))


@router.get(
    "/mine",
    response_model=list[MapLayerRequestResponse],
    summary="List my map-layer update requests",
)
async def my_requests(
    user: CurrentUser, db: DatabaseDep
) -> list[MapLayerRequestResponse]:
    """List the caller's own map-layer update requests."""
    rows = await db.fetch(
        f"select {_COLS} from public.map_layer_update_requests "
        "where requested_by = $1 order by created_at desc",
        user.id,
    )
    return [MapLayerRequestResponse.model_validate(_row_to_dict(r)) for r in rows]


@router.get(
    "",
    response_model=list[MapLayerRequestResponse],
    summary="List map-layer update requests (admin)",
)
async def list_requests(
    admin: AdminUser,
    db: DatabaseDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[MapLayerRequestResponse]:
    """List map-layer update requests, optionally filtered by status (admin)."""
    if status_filter is not None:
        rows = await db.fetch(
            f"select {_COLS} from public.map_layer_update_requests "
            "where status = $1::public.request_status order by created_at desc",
            status_filter,
        )
    else:
        rows = await db.fetch(
            f"select {_COLS} from public.map_layer_update_requests order by created_at desc"
        )
    return [MapLayerRequestResponse.model_validate(_row_to_dict(r)) for r in rows]


@router.post(
    "/{request_id}/approve",
    response_model=MapLayerRequestResponse,
    summary="Approve a request (admin) — applies the change",
)
async def approve_request(
    request_id: UUID, payload: MapLayerReviewRequest, admin: AdminUser, db: DatabaseDep
) -> MapLayerRequestResponse:
    """Approve a pending request and apply the proposed change to the target layer."""
    req = await db.fetchrow(
        """
        select layer_type::text as layer_type, operation::text as operation,
               target_id, proposed_data, status::text as status
        from public.map_layer_update_requests
        where id = $1
        """,
        request_id,
    )
    if req is None:
        raise NotFoundError("Request not found.")
    if req["status"] != "pending":
        raise ConflictError("This request has already been reviewed.")

    pd = req["proposed_data"]
    proposed = json.loads(pd) if isinstance(pd, str) else (pd or {})
    affected = await apply_map_layer_request(
        db, req["layer_type"], req["operation"], req["target_id"], proposed
    )

    row = await db.fetchrow(
        f"""
        update public.map_layer_update_requests
           set status = 'approved', applied_at = now(), reviewed_by = $2,
               reviewed_at = now(), review_notes = $3
         where id = $1
        returning {_COLS}
        """,
        request_id,
        admin.id,
        payload.notes,
    )
    assert row is not None
    log.info(
        "map_layer_request_approved",
        request_id=str(request_id),
        affected_id=str(affected),
        by=str(admin.id),
    )
    return MapLayerRequestResponse.model_validate(_row_to_dict(row))


@router.post(
    "/{request_id}/reject",
    response_model=MapLayerRequestResponse,
    summary="Reject a request (admin)",
)
async def reject_request(
    request_id: UUID, payload: MapLayerReviewRequest, admin: AdminUser, db: DatabaseDep
) -> MapLayerRequestResponse:
    """Reject a pending map-layer update request (admin)."""
    row = await db.fetchrow(
        f"""
        update public.map_layer_update_requests
           set status = 'rejected', reviewed_by = $2, reviewed_at = now(),
               review_notes = $3
         where id = $1 and status = 'pending'
        returning {_COLS}
        """,
        request_id,
        admin.id,
        payload.notes,
    )
    if row is None:
        raise NotFoundError("No pending request found for that id.")
    log.info("map_layer_request_rejected", request_id=str(request_id), by=str(admin.id))
    return MapLayerRequestResponse.model_validate(_row_to_dict(row))