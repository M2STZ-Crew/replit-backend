"""Alarm-raise request endpoints (Phase 13, Section 6).

Fire Volunteer (or BFP) sub-admins raise an alarm request on an incident; BFP
sub-admins execute (apply areas.alarm_level + alarm_level_set_by, validated by the
enforce_alarm_authority DB trigger) or reject. The execute broadcasts to the
incident's WebSocket channel.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.realtime.manager import manager
from app.schemas.alarm import AlarmRequestCreate, AlarmRequestResponse, AlarmReviewRequest
from app.schemas.auth import AuthenticatedUser

log = get_logger(__name__)

router = APIRouter(prefix="/alarm-requests", tags=["alarm-requests"])

_COLS = (
    "id, area_id, requested_by, "
    "requested_alarm_level::text as requested_alarm_level, justification, "
    "status::text as status, reviewed_by, reviewed_at, review_notes, executed_at, "
    "created_at, updated_at"
)


def _is_bfp_subadmin(user: AuthenticatedUser) -> bool:
    """True for a BFP sub-admin (the alarm execution authority)."""
    return user.role == "sub_admin" and user.agency_type == "bfp"


@router.post(
    "",
    response_model=AlarmRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise an alarm request (Fire-Vol/BFP sub-admin)",
)
async def create_alarm_request(
    payload: AlarmRequestCreate, user: StaffUser, db: DatabaseDep
) -> AlarmRequestResponse:
    """Submit a pending alarm-raise request for an active incident."""
    if not (user.role == "sub_admin" and user.agency_type in ("fire_volunteer", "bfp")):
        raise ForbiddenError(
            "Only a Fire Volunteer or BFP sub-admin may raise an alarm request."
        )
    area = await db.fetchrow(
        "select status::text as status from public.areas where id = $1", payload.area_id
    )
    if area is None:
        raise NotFoundError("Incident (area) not found.")
    if area["status"] in ("resolved", "rejected"):
        raise ConflictError("Cannot raise an alarm on a closed incident.")
    row = await db.fetchrow(
        f"""
        insert into public.alarm_requests
            (area_id, requested_by, requested_alarm_level, justification)
        values ($1, $2, $3::public.alarm_level, $4)
        returning {_COLS}
        """,
        payload.area_id,
        user.id,
        payload.requested_alarm_level,
        payload.justification,
    )
    assert row is not None
    log.info(
        "alarm_request_created",
        request_id=str(row["id"]),
        area_id=str(payload.area_id),
        level=payload.requested_alarm_level,
        by=str(user.id),
    )
    return AlarmRequestResponse.model_validate(dict(row))


@router.get(
    "/mine", response_model=list[AlarmRequestResponse], summary="List my alarm requests"
)
async def my_alarm_requests(
    user: CurrentUser, db: DatabaseDep
) -> list[AlarmRequestResponse]:
    """List the caller's own alarm requests."""
    rows = await db.fetch(
        f"select {_COLS} from public.alarm_requests where requested_by = $1 "
        "order by created_at desc",
        user.id,
    )
    return [AlarmRequestResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "",
    response_model=list[AlarmRequestResponse],
    summary="List alarm requests (BFP/admin)",
)
async def list_alarm_requests(
    user: StaffUser,
    db: DatabaseDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    area_id: Annotated[UUID | None, Query()] = None,
) -> list[AlarmRequestResponse]:
    """List alarm requests for review (BFP sub-admin or admin)."""
    if not (user.role == "admin" or _is_bfp_subadmin(user)):
        raise ForbiddenError("Only BFP sub-admins or admin may review alarm requests.")
    conditions: list[str] = []
    params: list[Any] = []
    if status_filter is not None:
        params.append(status_filter)
        conditions.append(f"status = ${len(params)}::public.request_status")
    if area_id is not None:
        params.append(area_id)
        conditions.append(f"area_id = ${len(params)}")
    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"select {_COLS} from public.alarm_requests {where_sql} order by created_at desc",
        *params,
    )
    return [AlarmRequestResponse.model_validate(dict(r)) for r in rows]


@router.post(
    "/{request_id}/execute",
    response_model=AlarmRequestResponse,
    summary="Execute (apply) an alarm request — BFP only",
)
async def execute_alarm_request(
    request_id: UUID, payload: AlarmReviewRequest, user: StaffUser, db: DatabaseDep
) -> AlarmRequestResponse:
    """Apply the requested alarm level to the incident (BFP sub-admin only)."""
    if not _is_bfp_subadmin(user):
        raise ForbiddenError("Only a BFP sub-admin may execute alarm requests (Section 6).")
    req = await db.fetchrow(
        """
        select area_id, requested_alarm_level::text as lvl, status::text as status
        from public.alarm_requests
        where id = $1
        """,
        request_id,
    )
    if req is None:
        raise NotFoundError("Alarm request not found.")
    if req["status"] != "pending":
        raise ConflictError("This alarm request has already been reviewed.")

    # The enforce_alarm_authority trigger validates BFP authority and stamps the time.
    await db.execute(
        """
        update public.areas
           set alarm_level = $2::public.alarm_level, alarm_level_set_by = $3
         where id = $1
        """,
        req["area_id"],
        req["lvl"],
        user.id,
    )
    row = await db.fetchrow(
        f"""
        update public.alarm_requests
           set status = 'approved', reviewed_by = $2, reviewed_at = now(),
               executed_at = now(), review_notes = $3
         where id = $1
        returning {_COLS}
        """,
        request_id,
        user.id,
        payload.notes,
    )
    assert row is not None
    await manager.broadcast(
        f"incident:{req['area_id']}",
        {
            "type": "alarm_raised",
            "area_id": str(req["area_id"]),
            "alarm_level": req["lvl"],
            "set_by": str(user.id),
        },
    )
    log.info(
        "alarm_request_executed",
        request_id=str(request_id),
        area_id=str(req["area_id"]),
        level=req["lvl"],
        by=str(user.id),
    )
    return AlarmRequestResponse.model_validate(dict(row))


@router.post(
    "/{request_id}/reject",
    response_model=AlarmRequestResponse,
    summary="Reject an alarm request — BFP only",
)
async def reject_alarm_request(
    request_id: UUID, payload: AlarmReviewRequest, user: StaffUser, db: DatabaseDep
) -> AlarmRequestResponse:
    """Reject a pending alarm request (BFP sub-admin only)."""
    if not _is_bfp_subadmin(user):
        raise ForbiddenError("Only a BFP sub-admin may reject alarm requests.")
    row = await db.fetchrow(
        f"""
        update public.alarm_requests
           set status = 'rejected', reviewed_by = $2, reviewed_at = now(),
               review_notes = $3
         where id = $1 and status = 'pending'
        returning {_COLS}
        """,
        request_id,
        user.id,
        payload.notes,
    )
    if row is None:
        raise NotFoundError("No pending alarm request found for that id.")
    log.info("alarm_request_rejected", request_id=str(request_id), by=str(user.id))
    return AlarmRequestResponse.model_validate(dict(row))