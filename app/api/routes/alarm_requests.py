"""Alarm-raise request endpoints (Phase 13, Section 6).

Fire Volunteer (or BFP) sub-admins raise an alarm request on an incident; BFP
sub-admins execute (apply areas.alarm_level + alarm_level_set_by, validated by the
enforce_alarm_authority DB trigger) or reject. The execute broadcasts to the
incident's WebSocket channel.

In the Admin console (PRD v14 §3.4, §4.7; pass 6 A45, A46): a Fire Volunteer
organisation's Admin asks BFP to raise the alarm on an incident routed to it,
and the BFP Admin decides — the same acts as their Coordinators on mobile.

A request still waiting can be cancelled, and any request BFP did not approve
can be deleted, by whoever asked, an Admin of their organisation, or the
system Admin. An approved request stays: it is the record of why the alarm
level changed.

How a request travels (27 Oct 2026):

- **Not asked for: Positive Fire Alarm.** It is the Area's initial
  classification, set by the first verify (the enforce_alarm_authority trigger).
  Requests begin at 1st Alarm.
- **Asked.** One open request per asker and Area: asking again for the same
  level — a second tap, or a retry after a reply was lost — answers with the
  request already waiting (HTTP 200) and sends nothing twice; asking for a
  different level replaces the asker's waiting one. The level must be above
  the Area's current one, and the Area must still be live.
- **Delivered.** Every BFP Coordinator's phone gets a push with the fire
  sound (FCM, for a phone with the app closed or locked), and every open
  BFP queue and the asker's LIVE screen hear it over the WebSocket
  (``agency:bfp`` and ``incident:<area>``), so the queue updates without a
  refresh. The request is stored first: a BFP Coordinator who was offline
  finds it waiting.
- **Answered.** Setting the level and closing the request happen in one
  transaction with the row locked, so two BFP Coordinators answering at once
  cannot both succeed; a level that would not raise the alarm, or an Area
  that has ended, is refused. The asker gets a push with the answer, and the
  same WebSocket channels carry it to every open screen.
- **Recorded.** Every ask, answer and withdrawal writes an audit row in the
  same transaction as the change (who, when, what level).
"""

from __future__ import annotations

from typing import Annotated, Any, get_args
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.realtime.events import broadcast_alarm_request
from app.realtime.manager import manager
from app.schemas.alarm import (
    INITIAL_ALARM_LEVEL,
    AlarmLevel,
    AlarmRequestCreate,
    AlarmRequestResponse,
    AlarmReviewRequest,
    RequestStatus,
    alarm_label,
)
from app.schemas.auth import AuthenticatedUser
from app.services.access import DECIDE_ALARM, REQUEST_ALARM, admin_access
from app.services.audit import record_audit
from app.services.incident import OFF_FEED_STATUSES, assert_admin_routed
from app.services.incident_notify import (
    notify_alarm_request_answered,
    notify_bfp_alarm_request,
)
from app.services.map_feed import publish_area_change

log = get_logger(__name__)

router = APIRouter(prefix="/alarm-requests", tags=["alarm-requests"])

# The ladder, lowest first (the alarm_level enum's own order).
_LADDER: tuple[str, ...] = get_args(AlarmLevel)

# Everything a screen shows about one request: the Area it is for (where, how
# far along, at what level now), who asked and for which organisation, and who
# answered.
_DETAIL_SQL = """
select a.id, a.area_id, ar.designation as area_designation,
       ar.status::text as area_status, ar.alarm_level::text as area_alarm_level,
       ar.centroid_lat as area_centroid_lat, ar.centroid_lng as area_centroid_lng,
       a.requested_by, u.full_name as requested_by_name,
       u.primary_org_id as requested_by_organization_id,
       o.name as requested_by_organization_name,
       a.requested_alarm_level::text as requested_alarm_level, a.justification,
       a.status::text as status, a.reviewed_by, rv.full_name as reviewed_by_name,
       a.reviewed_at, a.review_notes, a.executed_at, a.created_at, a.updated_at
from public.alarm_requests a
left join public.areas ar on ar.id = a.area_id
left join public.users u on u.id = a.requested_by
left join public.organizations o on o.id = u.primary_org_id
left join public.users rv on rv.id = a.reviewed_by
"""


def _rank(level: str | None) -> int:
    """Where a level sits on the ladder; no level yet is below all of them."""
    return _LADDER.index(level) if level in _LADDER else -1


def _area_name(designation: Any) -> str:
    text = str(designation or "").strip()
    if not text:
        return "This Area"
    return text if text.lower().startswith("area") else f"Area {text}"


def _is_bfp_subadmin(user: AuthenticatedUser) -> bool:
    """True for a BFP sub-admin (the alarm execution authority)."""
    return user.role == "sub_admin" and user.agency_type == "bfp"


def _may_decide(user: AuthenticatedUser) -> bool:
    """A BFP Coordinator, or the BFP Admin in the console (PRD v14 §3.4)."""
    access = admin_access(user)
    return _is_bfp_subadmin(user) or (access is not None and access.can(DECIDE_ALARM))


def _may_withdraw(
    user: AuthenticatedUser, requested_by: UUID, requester_org: UUID | None
) -> bool:
    """Whoever asked, an Admin of their (active) organisation, or the system Admin."""
    if user.id == requested_by:
        return True
    access = admin_access(user)
    if access is None:
        return False
    if access.is_system:
        return True
    # A turned-off organisation's Admin has no permissions: it may look, not act.
    return (
        bool(access.permissions)
        and requester_org is not None
        and access.organization_id == requester_org
    )


async def _withdrawable(
    db: Database, request_id: UUID, user: AuthenticatedUser
) -> asyncpg.Record:
    """The request, once the caller is someone who may cancel or delete it."""
    row = await db.fetchrow(
        """
        select a.status::text as status, a.requested_by, a.area_id,
               u.primary_org_id as requester_org
        from public.alarm_requests a
        left join public.users u on u.id = a.requested_by
        where a.id = $1
        """,
        request_id,
    )
    if row is None:
        raise NotFoundError("Alarm request not found.")
    if not _may_withdraw(user, row["requested_by"], row["requester_org"]):
        raise ForbiddenError(
            "Only whoever asked, an Admin of their organization, or the system Admin "
            "may cancel or delete this request."
        )
    return row


def _may_request(user: AuthenticatedUser) -> bool:
    """Fire Volunteer or BFP Coordinators, a Fire Volunteer responder in the
    field, or a Fire Volunteer organisation's Admin in the console (A45)."""
    access = admin_access(user)
    if access is not None:
        return access.can(REQUEST_ALARM)
    return (user.role == "sub_admin" and user.agency_type in ("fire_volunteer", "bfp")) or (
        user.role == "response_team" and user.agency_type == "fire_volunteer"
    )


async def _detail(db: Database, request_id: UUID) -> AlarmRequestResponse:
    row = await db.fetchrow(f"{_DETAIL_SQL} where a.id = $1", request_id)
    if row is None:
        raise NotFoundError("Alarm request not found.")
    return AlarmRequestResponse.model_validate(dict(row))


async def _announce(detail: AlarmRequestResponse, event: str) -> None:
    """Tell every open BFP queue and the Area's screens; never fail the act."""
    try:
        await broadcast_alarm_request(detail.model_dump(mode="json"), event)
    except Exception:
        log.error("alarm_request_broadcast_failed", request_id=str(detail.id), exc_info=True)


@router.post(
    "",
    response_model=AlarmRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise an alarm request (Fire-Vol/BFP sub-admin)",
)
async def create_alarm_request(
    payload: AlarmRequestCreate,
    request: Request,
    response: Response,
    user: StaffUser,
    db: DatabaseDep,
) -> AlarmRequestResponse:
    """Submit a pending alarm-raise request for an active incident.

    The same ask again (a double tap, a retry after a lost reply) answers 200
    with the request already waiting; a different level replaces the asker's
    waiting request for this Area.
    """
    # Fire-Vol/BFP sub-admins, or a fire-volunteer responder in the field, may
    # request an alarm raise; BFP sub-admins still execute it (Section 6). In the
    # console, a Fire Volunteer organisation's Admin asks too.
    if not _may_request(user):
        raise ForbiddenError(
            "Only Fire Volunteer responders, Coordinators and Admins, or BFP "
            "Coordinators, may raise an alarm request."
        )
    await assert_admin_routed(db, payload.area_id, user, "ask BFP to raise its alarm")
    level = payload.requested_alarm_level
    # A refusal in words rather than a 422: an older app still offers this level.
    if level == INITIAL_ALARM_LEVEL:
        raise ConflictError(
            f"{alarm_label(level)} is set automatically when a fire is verified. "
            "Ask BFP for 1st alarm or higher."
        )
    replaced: list[UUID] = []
    existing: UUID | None = None
    new_id: UUID | None = None
    async with db.acquire() as conn, conn.transaction():
        # Two taps, or a retry racing the first reply, wait here for each other.
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"alarm-request:{payload.area_id}:{user.id}",
        )
        area = await conn.fetchrow(
            "select status::text as status, alarm_level::text as alarm_level, designation "
            "from public.areas where id = $1",
            payload.area_id,
        )
        if area is None:
            raise NotFoundError("Incident (area) not found.")
        if area["status"] in OFF_FEED_STATUSES:
            raise ConflictError("Cannot raise an alarm on a closed incident.")
        if _rank(level) <= _rank(area["alarm_level"]):
            raise ConflictError(
                f"{_area_name(area['designation'])} is already at "
                f"{alarm_label(area['alarm_level'])}. Ask for a higher level."
            )
        waiting = await conn.fetch(
            "select id, requested_alarm_level::text as level from public.alarm_requests "
            "where area_id = $1 and requested_by = $2 and status = 'pending'",
            payload.area_id,
            user.id,
        )
        existing = next((r["id"] for r in waiting if r["level"] == level), None)
        if existing is None:
            for r in waiting:
                await conn.execute(
                    """
                    update public.alarm_requests
                       set status = 'cancelled', reviewed_by = $2, reviewed_at = now(),
                           review_notes = $3
                     where id = $1 and status = 'pending'
                    """,
                    r["id"],
                    user.id,
                    f"Replaced by a request for {alarm_label(level)}.",
                )
                replaced.append(r["id"])
            new_id = await conn.fetchval(
                """
                insert into public.alarm_requests
                    (area_id, requested_by, requested_alarm_level, justification)
                values ($1, $2, $3::public.alarm_level, $4)
                returning id
                """,
                payload.area_id,
                user.id,
                level,
                payload.justification,
            )
            await record_audit(
                conn,
                request,
                user,
                action="alarm.request",
                entity_type="alarm_request",
                entity_id=new_id,
                area_id=payload.area_id,
                after_state={
                    "requested_alarm_level": level,
                    "justification": payload.justification,
                    "current_alarm_level": area["alarm_level"],
                    "replaces": [str(r) for r in replaced],
                },
            )

    if existing is not None:
        # Already waiting: say so, and send nothing twice.
        response.status_code = status.HTTP_200_OK
        log.info("alarm_request_repeated", request_id=str(existing), by=str(user.id))
        return await _detail(db, existing)

    assert new_id is not None
    detail = await _detail(db, new_id)
    for old in replaced:
        await _announce(await _detail(db, old), "cancelled")
    await _announce(detail, "requested")
    log.info(
        "alarm_request_created",
        request_id=str(new_id),
        area_id=str(payload.area_id),
        level=level,
        by=str(user.id),
        replaced=len(replaced),
    )
    try:
        await notify_bfp_alarm_request(
            db,
            payload.area_id,
            user.id,
            level,
            request_id=new_id,
            organization=detail.requested_by_organization_name,
        )
    except Exception:
        log.error("bfp_alarm_notify_failed", area_id=str(payload.area_id), exc_info=True)
    return detail


@router.get(
    "/mine", response_model=list[AlarmRequestResponse], summary="List my alarm requests"
)
async def my_alarm_requests(
    user: CurrentUser,
    db: DatabaseDep,
    area_id: Annotated[UUID | None, Query()] = None,
) -> list[AlarmRequestResponse]:
    """List the caller's own alarm requests, newest first (optionally one Area's)."""
    rows = await db.fetch(
        f"""
        {_DETAIL_SQL}
        where a.requested_by = $1 and ($2::uuid is null or a.area_id = $2)
        order by a.created_at desc
        """,
        user.id,
        area_id,
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
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
    area_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AlarmRequestResponse]:
    """List alarm requests for review (BFP sub-admin or admin).

    Waiting requests first, then the newest, at most ``limit`` rows: BFP's
    queue re-reads this on every change and every 15 s, so the history it
    carries stays bounded however long the system runs.
    """
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
    params.append(limit)
    rows = await db.fetch(
        f"{_DETAIL_SQL} {where_sql} "
        f"order by (a.status = 'pending') desc, a.created_at desc limit ${len(params)}",
        *params,
    )
    return [AlarmRequestResponse.model_validate(dict(r)) for r in rows]


@router.post(
    "/{request_id}/execute",
    response_model=AlarmRequestResponse,
    summary="Execute (apply) an alarm request — BFP only",
)
async def execute_alarm_request(
    request_id: UUID,
    payload: AlarmReviewRequest,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> AlarmRequestResponse:
    """Apply the requested alarm level to the incident (BFP Coordinator or Admin).

    The request row is locked first, so two answers at once cannot both pass;
    the level must raise the Area's alarm, and the Area must still be live.
    """
    if not _may_decide(user):
        raise ForbiddenError(
            "Only BFP sets the alarm level: a BFP Coordinator on the mobile app, or "
            "the BFP Admin here (Section 6)."
        )
    async with db.acquire() as conn, conn.transaction():
        req = await conn.fetchrow(
            """
            select area_id, requested_alarm_level::text as lvl, status::text as status
            from public.alarm_requests
            where id = $1
            for update
            """,
            request_id,
        )
        if req is None:
            raise NotFoundError("Alarm request not found.")
        if req["status"] != "pending":
            raise ConflictError("This alarm request has already been reviewed.")
        area = await conn.fetchrow(
            "select status::text as status, alarm_level::text as alarm_level, designation "
            "from public.areas where id = $1 for update",
            req["area_id"],
        )
        if area is None:
            raise NotFoundError("Incident (area) not found.")
        if area["status"] in OFF_FEED_STATUSES:
            raise ConflictError(
                f"{_area_name(area['designation'])} has ended, so its alarm level stays "
                "as it is. Decline the request instead."
            )
        if _rank(req["lvl"]) <= _rank(area["alarm_level"]):
            raise ConflictError(
                f"{_area_name(area['designation'])} is already at "
                f"{alarm_label(area['alarm_level'])}. Decline this request instead."
            )

        # The enforce_alarm_authority trigger validates BFP authority and stamps the time.
        try:
            await conn.execute(
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
        await conn.execute(
            """
            update public.alarm_requests
               set status = 'approved', reviewed_by = $2, reviewed_at = now(),
                   executed_at = now(), review_notes = $3
             where id = $1
            """,
            request_id,
            user.id,
            payload.notes,
        )
        await record_audit(
            conn,
            request,
            user,
            action="alarm.execute",
            entity_type="alarm_request",
            entity_id=request_id,
            area_id=req["area_id"],
            before_state={"alarm_level": area["alarm_level"]},
            after_state={"alarm_level": req["lvl"]},
            metadata={"notes": payload.notes} if payload.notes else None,
        )

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
    detail = await _detail(db, request_id)
    await _announce(detail, "approved")
    await _tell_asker(db, detail)
    log.info(
        "alarm_request_executed",
        request_id=str(request_id),
        area_id=str(req["area_id"]),
        level=req["lvl"],
        by=str(user.id),
    )
    return detail


@router.post(
    "/{request_id}/reject",
    response_model=AlarmRequestResponse,
    summary="Reject an alarm request — BFP only",
)
async def reject_alarm_request(
    request_id: UUID,
    payload: AlarmReviewRequest,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> AlarmRequestResponse:
    """Reject a pending alarm request (BFP Coordinator or Admin)."""
    if not _may_decide(user):
        raise ForbiddenError(
            "Only BFP (a Coordinator or the BFP Admin) may decline alarm requests."
        )
    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            update public.alarm_requests
               set status = 'rejected', reviewed_by = $2, reviewed_at = now(),
                   review_notes = $3
             where id = $1 and status = 'pending'
            returning area_id
            """,
            request_id,
            user.id,
            payload.notes,
        )
        if row is None:
            raise NotFoundError("No pending alarm request found for that id.")
        await record_audit(
            conn,
            request,
            user,
            action="alarm.reject",
            entity_type="alarm_request",
            entity_id=request_id,
            area_id=row["area_id"],
            metadata={"notes": payload.notes} if payload.notes else None,
        )
    detail = await _detail(db, request_id)
    await _announce(detail, "rejected")
    await _tell_asker(db, detail)
    log.info("alarm_request_rejected", request_id=str(request_id), by=str(user.id))
    return detail


async def _tell_asker(db: Database, detail: AlarmRequestResponse) -> None:
    """The asker hears BFP's answer on their phone; never fail the answer."""
    try:
        await notify_alarm_request_answered(db, detail)
    except Exception:
        log.error("alarm_answer_notify_failed", request_id=str(detail.id), exc_info=True)


@router.post(
    "/{request_id}/cancel",
    response_model=AlarmRequestResponse,
    summary="Cancel a pending alarm request (whoever asked)",
)
async def cancel_alarm_request(
    request_id: UUID,
    payload: AlarmReviewRequest,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> AlarmRequestResponse:
    """Withdraw a request BFP has not answered; it moves to the history as Cancelled."""
    found = await _withdrawable(db, request_id, user)
    try:
        async with db.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                update public.alarm_requests
                   set status = 'cancelled', reviewed_by = $2, reviewed_at = now(),
                       review_notes = $3
                 where id = $1 and status = 'pending'
                returning id
                """,
                request_id,
                user.id,
                payload.notes,
            )
            if row is None:
                # Answered (or cancelled) between the read and the write.
                raise ConflictError("BFP has already answered this request.")
            await record_audit(
                conn,
                request,
                user,
                action="alarm.cancel",
                entity_type="alarm_request",
                entity_id=request_id,
                area_id=found["area_id"],
                metadata={"notes": payload.notes} if payload.notes else None,
            )
    except asyncpg.InvalidTextRepresentationError as exc:
        # request_status gains 'cancelled' in migration 20261024090000.
        log.warning("alarm_cancel_before_migration", error=str(exc))
        raise ConflictError(
            "The database cannot record a cancelled request yet. Delete the request "
            "instead, or apply the latest database migration."
        ) from exc
    detail = await _detail(db, request_id)
    await _announce(detail, "cancelled")
    log.info("alarm_request_cancelled", request_id=str(request_id), by=str(user.id))
    return detail


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alarm request BFP did not approve (whoever asked)",
)
async def delete_alarm_request(
    request_id: UUID, request: Request, user: StaffUser, db: DatabaseDep
) -> Response:
    """Remove a pending, declined or cancelled request; an approved one stays."""
    row = await _withdrawable(db, request_id, user)
    if row["status"] == "approved":
        raise ConflictError(
            "BFP approved this request, so it stays: it is the record of why the "
            "alarm level changed."
        )
    detail = await _detail(db, request_id)
    async with db.acquire() as conn, conn.transaction():
        deleted = await conn.fetchval(
            "delete from public.alarm_requests where id = $1 and status <> 'approved' "
            "returning id",
            request_id,
        )
        if deleted is None:
            # Approved (or already gone) between the read and the delete.
            raise ConflictError("This request was just answered or removed. Refresh the list.")
        await record_audit(
            conn,
            request,
            user,
            action="alarm.delete",
            entity_type="alarm_request",
            entity_id=request_id,
            area_id=row["area_id"],
            before_state={
                "status": row["status"],
                "requested_alarm_level": detail.requested_alarm_level,
            },
        )
    await _announce(detail, "deleted")
    log.info("alarm_request_deleted", request_id=str(request_id), by=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
