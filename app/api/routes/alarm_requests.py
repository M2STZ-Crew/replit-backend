"""Alarm-raise request endpoints (Phase 13, Section 6).

Fire Volunteer (or BFP) sub-admins raise an alarm request on an incident; BFP
sub-admins execute (apply areas.alarm_level + alarm_level_set_by, validated by the
enforce_alarm_authority DB trigger) or reject. The execute broadcasts to the
incident's WebSocket channel.

In the Admin console (PRD v14 §3.4, §4.7; pass 6 A45, A46): a Fire Volunteer
organisation's Admin asks BFP to raise the alarm on an incident routed to it,
and the BFP Admin decides — the same acts as their Coordinators on mobile.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.realtime.manager import manager
from app.schemas.alarm import AlarmRequestCreate, AlarmRequestResponse, AlarmReviewRequest
from app.schemas.auth import AuthenticatedUser
from app.services.access import DECIDE_ALARM, REQUEST_ALARM, admin_access
from app.services.incident import OFF_FEED_STATUSES, assert_admin_routed
from app.services.incident_notify import notify_bfp_alarm_request
from app.services.map_feed import publish_area_change

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


def _may_decide(user: AuthenticatedUser) -> bool:
    """A BFP Coordinator, or the BFP Admin in the console (PRD v14 §3.4)."""
    access = admin_access(user)
    return _is_bfp_subadmin(user) or (access is not None and access.can(DECIDE_ALARM))


def _may_request(user: AuthenticatedUser) -> bool:
    """Fire Volunteer or BFP Coordinators, a Fire Volunteer responder in the
    field, or a Fire Volunteer organisation's Admin in the console (A45)."""
    access = admin_access(user)
    if access is not None:
        return access.can(REQUEST_ALARM)
    return (user.role == "sub_admin" and user.agency_type in ("fire_volunteer", "bfp")) or (
        user.role == "response_team" and user.agency_type == "fire_volunteer"
    )


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
    # Fire-Vol/BFP sub-admins, or a fire-volunteer responder in the field, may
    # request an alarm raise; BFP sub-admins still execute it (Section 6). In the
    # console, a Fire Volunteer organisation's Admin asks too.
    if not _may_request(user):
        raise ForbiddenError(
            "Only Fire Volunteer responders, Coordinators and Admins, or BFP "
            "Coordinators, may raise an alarm request."
        )
    area = await db.fetchrow(
        "select status::text as status from public.areas where id = $1", payload.area_id
    )
    if area is None:
        raise NotFoundError("Incident (area) not found.")
    if area["status"] in OFF_FEED_STATUSES:
        raise ConflictError("Cannot raise an alarm on a closed incident.")
    await assert_admin_routed(db, payload.area_id, user, "ask BFP to raise its alarm")
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
    try:
        await notify_bfp_alarm_request(
            db, payload.area_id, user.id, payload.requested_alarm_level
        )
    except Exception:
        log.error("bfp_alarm_notify_failed", area_id=str(payload.area_id), exc_info=True)
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
        conditions.append(f"a.status = ${len(params)}::public.request_status")
    if area_id is not None:
        params.append(area_id)
        conditions.append(f"a.area_id = ${len(params)}")
    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"""
        select a.id, a.area_id, ar.designation as area_designation, a.requested_by,
               u.full_name as requested_by_name,
               a.requested_alarm_level::text as requested_alarm_level, a.justification,
               a.status::text as status, a.reviewed_by, a.reviewed_at, a.review_notes,
               a.executed_at, a.created_at, a.updated_at
        from public.alarm_requests a
        left join public.areas ar on ar.id = a.area_id
        left join public.users u on u.id = a.requested_by
        {where_sql}
        order by a.created_at desc
        """,
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
    """Apply the requested alarm level to the incident (BFP Coordinator or Admin)."""
    if not _may_decide(user):
        raise ForbiddenError(
            "Only BFP sets the alarm level: a BFP Coordinator on the mobile app, or "
            "the BFP Admin here (Section 6)."
        )
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
    try:
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
    except asyncpg.InsufficientPrivilegeError as exc:
        # The trigger let only BFP Coordinators set a level before migration
        # 20261023180000; on a database without it the BFP Admin is refused.
        log.warning("alarm_execute_refused_by_db", by=str(user.id), error=str(exc))
        raise ForbiddenError(
            "The database does not let an Admin account set the alarm level yet. "
            "A BFP Coordinator can set it from the mobile app."
        ) from exc
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
    await publish_area_change(db, req["area_id"])
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
    """Reject a pending alarm request (BFP Coordinator or Admin)."""
    if not _may_decide(user):
        raise ForbiddenError(
            "Only BFP (a Coordinator or the BFP Admin) may decline alarm requests."
        )
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