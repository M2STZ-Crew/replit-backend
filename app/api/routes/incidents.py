"""Incident lifecycle endpoints (Phase 9-10, Sections 8-10).

The operational console over public.areas: a visibility-filtered feed, the
status-transition actions, the dispatch / response progression, and the live
responder GPS stream. Every state-changing action broadcasts to WebSocket
subscribers via app.realtime.events. Visibility is two-way between BFP and Fire
Volunteer; other agencies see only incidents whose member reports selected them;
admin sees everything.

Authority (Section 6 + the chosen coordinator/responder model). "Coordinator"
means admin, or a sub-admin of a fire agency (fire_volunteer / bfp); a police,
medical or barangay sub-admin observes only and changes no state:
  - verify ................ Fire Volunteer sub-admin only (DB-pinned by trigger)
  - reject / resolve ...... coordinator
  - dispatch (manual) ..... coordinator assigns a response_team user
  - self-dispatch ......... a response_team user selects themselves
  - en_route / arrived .... the assigned responder, or a coordinator
  - location stream ....... the assigned responder (response_team) only
  - accept ................ an observer sub-admin whose agency Admin routed it to
                            (v10 Section 2.6.1) — an acknowledgement, no status change
Fire out (resolve) moves the incident into the Post-Incident Report step; filing
that report — app/api/routes/post_incident_reports.py — is what closes it.
The matching *_at timestamp is stamped by a database trigger on each status change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, Request

from app.api.deps import DatabaseDep, StaffUser, StorageClientDep
from app.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.realtime.events import broadcast_incident_event, broadcast_responder_location
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import MessageResponse
from app.schemas.incident import (
    AvailableResponder,
    DispatchItem,
    IncidentDetail,
    IncidentRejectRequest,
    IncidentReportDetail,
    IncidentStats,
    IncidentSummary,
    ResponderLocationCreate,
    ResponderLocationItem,
    SelfDispatchRequest,
)
from app.services.audit import record_audit
from app.services.incident import (
    OFF_FEED_STATUSES,
    active_area_sql,
    assert_can_accept,
    assert_coordinator,
    assert_transition,
    is_coordinator,
    record_responder_location,
    visible_agencies,
)
from app.services.incident_notify import (
    notify_incident_reporters,
)

log = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

# Incident statuses during which a responder may attach themselves. v11 dropped
# 'dispatched' from the lifecycle; self-selection survives as the record of who
# is actually on an incident (it drives responder GPS and the Arrived button),
# but it no longer moves the status — Accept already did that.
_RESPONDER_ATTACHABLE = ("verified", "en_route", "arrived")

# Columns of IncidentSummary, selected from public.areas aliased ``a``. Shared by
# the feed and the detail so the two cannot drift. The three agency arrays are
# what the consoles key their per-agency sound and the Accept control on.
_SUMMARY_COLS = """
    a.id, a.designation, a.status::text as status,
    a.centroid_lat, a.centroid_lng, a.report_count,
    a.confidence_score, a.confidence_band::text as confidence_band,
    a.alarm_level::text as alarm_level,
    (select count(*) from public.dispatch_logs d
     where d.area_id = a.id and d.status = 'active') as active_dispatch_count,
    a.reported_at, a.verified_at, a.dispatched_at, a.en_route_at,
    a.arrived_at, a.resolved_at, a.post_incident_report_at, a.closed_at,
    a.rejected_at, a.merged_at, a.updated_at,
    coalesce((select array_agg(distinct ag order by ag)
              from public.area_reports ar
              join public.reports r on r.id = ar.report_id
              cross join lateral unnest(r.selected_agencies::text[]) as ag
              where ar.area_id = a.id), '{}') as requested_agencies,
    coalesce((select array_agg(distinct rt.agency::text)
              from public.area_routes rt
              where rt.area_id = a.id), '{}') as routed_agencies,
    coalesce((select array_agg(distinct rt.agency::text)
              from public.area_routes rt
              where rt.area_id = a.id and rt.accepted_at is not null), '{}')
        as accepted_agencies,
    (select count(*) from public.area_routes rt where rt.area_id = a.id) as route_count
"""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
async def _load_status(db: Database, incident_id: UUID) -> str:
    """Return the incident's current status, or raise 404 if it does not exist."""
    status_val = await db.fetchval(
        "select status::text from public.areas where id = $1", incident_id
    )
    if status_val is None:
        raise NotFoundError("Incident not found.")
    return str(status_val)


async def _lock_status(conn: asyncpg.Connection, incident_id: UUID) -> str:
    """Re-read the status under a row lock, inside the caller's transaction.

    Handlers still check with :func:`_load_status` first, so an ordinary refusal
    (404, 403, 409) costs no transaction. This read is the one the change and its
    audit row are based on: holding the lock means two coordinators acting at once
    cannot both pass the transition check, and the recorded "before" is exact.
    """
    status_val = await conn.fetchval(
        "select status::text from public.areas where id = $1 for update", incident_id
    )
    if status_val is None:
        raise NotFoundError("Incident not found.")
    return str(status_val)


async def _audit_transition(
    conn: asyncpg.Connection,
    request: Request,
    user: AuthenticatedUser,
    incident_id: UUID,
    *,
    action: str,
    before: str,
    after: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write a lifecycle action's audit row in the transaction that made the change.

    Replaces the request middleware for these actions (see _RULES in
    app/services/audit.py). That middleware runs after the response and swallows
    its own errors, so a verify or reject could succeed with no record; here a
    failed write rolls the action back. The row also carries the status the
    incident moved from and to, which the middleware could not see (Section 4.1).
    """
    await record_audit(
        conn,
        request,
        user,
        action=action,
        entity_type="area",
        entity_id=incident_id,
        area_id=incident_id,
        before_state={"status": before},
        after_state={"status": after},
        metadata=metadata,
    )


async def _assert_visible(db: Database, incident_id: UUID, user: AuthenticatedUser) -> None:
    """Raise 403 unless the incident is visible to the caller's agency (admin: always)."""
    agencies = visible_agencies(user)
    if agencies is None:
        return
    if not agencies:
        raise ForbiddenError("This incident is not visible to your agency.")
    visible = await db.fetchval(
        """
        select exists (
            select 1 from public.area_reports ar
            join public.reports r on r.id = ar.report_id
            where ar.area_id = $1
              and r.selected_agencies && $2::public.agency_type[]
        )
        """,
        incident_id,
        agencies,
    )
    if not visible:
        raise ForbiddenError("This incident is not visible to your agency.")


async def _active_dispatch_id(
    db: Database, incident_id: UUID, responder_id: UUID
) -> UUID | None:
    """Return the caller's active dispatch id for this incident, or None."""
    dispatch_id: UUID | None = await db.fetchval(
        """
        select id from public.dispatch_logs
        where area_id = $1 and responder_id = $2 and status = 'active'
        order by dispatched_at desc
        limit 1
        """,
        incident_id,
        responder_id,
    )
    return dispatch_id


async def _assert_responder_or_coordinator(
    db: Database, incident_id: UUID, user: AuthenticatedUser
) -> None:
    """Allow a coordinating sub-admin/admin, or a responder with an active dispatch."""
    if is_coordinator(user):
        return
    if user.role == "response_team" and await _active_dispatch_id(db, incident_id, user.id):
        return
    raise ForbiddenError(
        "Only an assigned responder or a sub-admin may advance the response."
    )


async def build_incident_detail(db: Database, incident_id: UUID) -> IncidentDetail:
    """Build the full IncidentDetail for an incident (assumes existence already checked)."""
    row = await db.fetchrow(
        f"""
        select {_SUMMARY_COLS},
               a.n_score, a.s_score, a.v_score, a.version, a.parent_area_id,
               a.verified_by, vu.full_name as verified_by_name,
               a.resolved_by, ru.full_name as resolved_by_name,
               a.closed_by, cu.full_name as closed_by_name,
               a.rejected_by, ju.full_name as rejected_by_name,
               a.rejection_reason,
               a.merged_by, mu.full_name as merged_by_name, a.merged_into_area_id,
               a.alarm_level_set_by, a.alarm_level_set_at,
               exists (select 1 from public.post_incident_reports p
                       where p.area_id = a.id) as has_post_incident_report
        from public.areas a
        left join public.users vu on vu.id = a.verified_by
        left join public.users ru on ru.id = a.resolved_by
        left join public.users cu on cu.id = a.closed_by
        left join public.users ju on ju.id = a.rejected_by
        left join public.users mu on mu.id = a.merged_by
        where a.id = $1
        """,
        incident_id,
    )
    if row is None:
        raise NotFoundError("Incident not found.")
    routes = await db.fetch(
        """
        select rt.id, rt.agency::text as agency, rt.organization_id,
               o.name as organization_name,
               rt.routed_by, rb.full_name as routed_by_name, rt.routed_at,
               rt.accepted_by, ab.full_name as accepted_by_name, rt.accepted_at
        from public.area_routes rt
        left join public.organizations o on o.id = rt.organization_id
        left join public.users rb on rb.id = rt.routed_by
        left join public.users ab on ab.id = rt.accepted_by
        where rt.area_id = $1
        order by rt.routed_at asc, rt.agency, o.name nulls first
        """,
        incident_id,
    )
    reports = await db.fetch(
        """
        select r.id, r.device_lat, r.device_lng, r.has_exif, r.gps_discrepancy_flag,
               r.user_verified_percent, r.selected_agencies::text[] as selected_agencies,
               r.created_at
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        where ar.area_id = $1
        order by r.created_at asc
        """,
        incident_id,
    )
    data = dict(row)
    data["routes"] = [dict(r) for r in routes]
    data["reports"] = [dict(r) for r in reports]
    return IncidentDetail.model_validate(data)


async def finish_incident_change(
    db: Database, incident_id: UUID, event_type: str
) -> IncidentDetail:
    """Rebuild the detail, broadcast to subscribers, push the reporter, and return it.

    Public because the Post-Incident Report and Admin routing modules change
    incidents too, and their subscribers deserve the same broadcast.
    """
    detail = await build_incident_detail(db, incident_id)
    await broadcast_incident_event(detail, event_type)
    try:
        await notify_incident_reporters(db, incident_id, event_type)
    except Exception:
        log.error("reporter_notify_failed", incident_id=str(incident_id), exc_info=True)
    return detail


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[IncidentSummary], summary="List incidents visible to me")
async def list_incidents(
    user: StaffUser,
    db: DatabaseDep,
    active_only: bool = True,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[IncidentSummary]:
    """List incidents filtered to the caller's agency visibility (BFP<->Fire-Vol two-way)."""
    agencies = visible_agencies(user)
    if agencies is not None and not agencies:
        return []

    conditions: list[str] = []
    params: list[Any] = []

    if agencies is not None:
        params.append(agencies)
        conditions.append(
            "exists (select 1 from public.area_reports ar "
            "join public.reports r on r.id = ar.report_id "
            "where ar.area_id = a.id and "
            f"r.selected_agencies && ${len(params)}::public.agency_type[])"
        )
    if active_only:
        conditions.append(active_area_sql("a"))
    if status_filter is not None:
        params.append(status_filter)
        conditions.append(f"a.status = ${len(params)}::public.area_status")

    params.append(limit)
    limit_pos = len(params)
    params.append(offset)
    offset_pos = len(params)

    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"""
        select {_SUMMARY_COLS}
        from public.areas a
        {where_sql}
        order by a.reported_at desc
        limit ${limit_pos} offset ${offset_pos}
        """,
        *params,
    )
    return [IncidentSummary.model_validate(dict(r)) for r in rows]


@router.get("/stats", response_model=IncidentStats, summary="Responder dashboard counters")
async def incident_stats(user: StaffUser, db: DatabaseDep) -> IncidentStats:
    """Live counters for the responder dashboard, scoped to the caller's visibility."""
    agencies = visible_agencies(user)
    if agencies is None:  # admin: everything
        active = await db.fetchval(
            f"select count(*) from public.areas where {active_area_sql()}"
        )
        pending = await db.fetchval(
            "select count(*) from public.areas where status = 'reported'"
        )
        pending_reports = await db.fetchval(
            "select count(*) from public.areas where status = 'post_incident_report'"
        )
    elif not agencies:
        active = 0
        pending = 0
        pending_reports = 0
    else:
        visible = (
            "exists (select 1 from public.area_reports ar "
            "join public.reports r on r.id = ar.report_id "
            "where ar.area_id = a.id and r.selected_agencies && $1::public.agency_type[])"
        )
        active = await db.fetchval(
            f"select count(*) from public.areas a "
            f"where {active_area_sql('a')} and {visible}",
            agencies,
        )
        pending = await db.fetchval(
            f"select count(*) from public.areas a where a.status = 'reported' and {visible}",
            agencies,
        )
        pending_reports = await db.fetchval(
            f"select count(*) from public.areas a "
            f"where a.status = 'post_incident_report' and {visible}",
            agencies,
        )

    my_agency = user.agency_type
    if my_agency:
        deployed = await db.fetchval(
            "select count(distinct d.responder_id) from public.dispatch_logs d "
            "join public.users u on u.id = d.responder_id "
            "where d.status = 'active' and u.agency_type = $1::public.agency_type",
            my_agency,
        )
        roster = await db.fetchval(
            "select count(*) from public.users "
            "where role = 'response_team' and agency_type = $1::public.agency_type",
            my_agency,
        )
    else:
        deployed = await db.fetchval(
            "select count(distinct responder_id) from public.dispatch_logs where status = 'active'"
        )
        roster = await db.fetchval(
            "select count(*) from public.users where role = 'response_team'"
        )

    deployed_n = int(deployed or 0)
    return IncidentStats(
        active_incidents=int(active or 0),
        pending_verify=int(pending or 0),
        units_deployed=deployed_n,
        units_standby=max(int(roster or 0) - deployed_n, 0),
        pending_reports=int(pending_reports or 0),
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetail,
    summary="Get one incident with its reports",
)
async def get_incident(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Return one incident (lifecycle + confidence + member reports), visibility-checked."""
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    return await build_incident_detail(db, incident_id)


@router.get(
    "/{incident_id}/reports",
    response_model=list[IncidentReportDetail],
    summary="List an incident's member reports (reviewer view)",
)
async def list_incident_reports(
    incident_id: UUID, user: StaffUser, db: DatabaseDep, storage: StorageClientDep
) -> list[IncidentReportDetail]:
    """Member reports with the reporter's name and a signed photo URL (sub-admin review)."""
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    rows = await db.fetch(
        """
        select r.id, r.reporter_id, u.full_name as reporter_name, r.photo_url,
               r.device_lat, r.device_lng, r.has_exif, r.gps_discrepancy_flag,
               r.user_verified_percent, r.selected_agencies::text[] as selected_agencies,
               r.notes, r.created_at
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        left join public.users u on u.id = r.reporter_id
        where ar.area_id = $1
        order by r.created_at asc
        """,
        incident_id,
    )
    items: list[IncidentReportDetail] = []
    for r in rows:
        signed: str | None = None
        if r["photo_url"]:
            try:
                signed = await storage.create_signed_url(
                    bucket="incident-photos", path=r["photo_url"]
                )
            except ExternalServiceError:
                signed = None
        data = dict(r)
        data["photo_url"] = signed
        data["selected_agencies"] = list(r["selected_agencies"] or [])
        items.append(IncidentReportDetail.model_validate(data))
    return items


# --------------------------------------------------------------------------- #
# Lifecycle decision transitions (v11 Section 2.5)
# --------------------------------------------------------------------------- #
# v11 replaced /verify with the collapsed Accept below: verifying and rolling
# were one decision in practice, and splitting them made responders wait for a
# coordinator to be free. See accept_incident.


@router.post(
    "/{incident_id}/reject",
    response_model=IncidentDetail,
    summary="Reject an incident as a false report (sub-admin)",
)
async def reject_incident(
    incident_id: UUID,
    payload: IncidentRejectRequest,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """Reject an incident (invalid / false report). Coordinating sub-admins, or admin."""
    assert_coordinator(user, "reject incidents")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    assert_transition(current, "rejected")
    async with db.acquire() as conn, conn.transaction():
        current = await _lock_status(conn, incident_id)
        assert_transition(current, "rejected")
        await conn.execute(
            """
            update public.areas
               set status = 'rejected', rejected_by = $2, rejection_reason = $3
             where id = $1
            """,
            incident_id,
            user.id,
            payload.reason,
        )
        await _audit_transition(
            conn, request, user, incident_id,
            action="incident.reject", before=current, after="rejected",
            metadata={"reason": payload.reason},
        )
    log.info("incident_rejected", incident_id=str(incident_id), user_id=str(user.id))
    return await finish_incident_change(db, incident_id, "incident_rejected")


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentDetail,
    summary="Mark the fire out (sub-admin)",
)
async def resolve_incident(
    incident_id: UUID,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """Fire out: end the response and open the Post-Incident Report step.

    Completes any still-active responder attachments. Fire out ends the
    response, not the incident: it passes through 'fire_out' (stamping
    resolved_at, whose column name v11 left alone) straight into
    'post_incident_report', where it waits in the captain's tray until the report
    is filed (Section 2.5.3). Both transitions are validated here and applied as
    two updates in one transaction with the audit row, so each passes through the
    database's own sequencing constraints and nothing observes the incident
    half-moved or unrecorded.
    """
    assert_coordinator(user, "mark incidents fire out")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    assert_transition(current, "fire_out")
    assert_transition("fire_out", "post_incident_report")
    async with db.acquire() as conn, conn.transaction():
        current = await _lock_status(conn, incident_id)
        assert_transition(current, "fire_out")
        await conn.execute(
            "update public.areas set status = 'fire_out', resolved_by = $2 where id = $1",
            incident_id,
            user.id,
        )
        await conn.execute(
            "update public.areas set status = 'post_incident_report' where id = $1",
            incident_id,
        )
        completed = await conn.fetch(
            """
            update public.dispatch_logs
               set status = 'completed', completed_at = now()
             where area_id = $1 and status = 'active'
            returning id
            """,
            incident_id,
        )
        await _audit_transition(
            conn, request, user, incident_id,
            action="incident.resolve", before=current, after="post_incident_report",
            metadata={"passed_through": "fire_out", "responders_completed": len(completed)},
        )
    log.info("incident_resolved", incident_id=str(incident_id), user_id=str(user.id))
    return await finish_incident_change(db, incident_id, "incident_resolved")


# --------------------------------------------------------------------------- #
# Accept — the collapsed act (v11 Section 2.5.1)
# --------------------------------------------------------------------------- #
@router.post(
    "/{incident_id}/accept",
    response_model=IncidentDetail,
    summary="Accept an incident: the first Accept verifies it and sends responders",
)
async def accept_incident(
    incident_id: UUID, request: Request, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Accept an incident. The first Accept moves it; later ones record participation.

    v11 collapsed verify-then-dispatch into this one act. The **first** Accept on
    an Area carries it ``reported -> verified -> en_route`` inside a single
    transaction, so responders can leave the moment someone commits rather than
    waiting for a second decision. Admin, Coordinators and Observers may all
    press it (Section 2.5.1); whoever gets there first wins.

    Every **later** Accept, from another responding agency, writes its own row
    and its own audit entry but leaves the status alone — it means "we are coming
    too", not "start again". Each agency's UI reads its own row back, so an
    operator can see whether their team is committed.

    Pressing twice as the same person is a no-op: the unique constraint on
    ``(area_id, user_id)`` makes Accept idempotent per actor (Section 11.1), and
    the partial unique index on ``is_first`` settles the race between two
    agencies in the database rather than in whichever transaction commits last.
    """
    assert_can_accept(user)
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    if current in OFF_FEED_STATUSES:
        raise ConflictError(
            "This incident is no longer live, so there is nothing to accept.",
            details={"current_status": current},
        )

    moved = False
    async with db.acquire() as conn, conn.transaction():
        current = await _lock_status(conn, incident_id)
        if current in OFF_FEED_STATUSES:
            raise ConflictError(
                "This incident is no longer live, so there is nothing to accept.",
                details={"current_status": current},
            )
        already = await conn.fetchval(
            "select exists (select 1 from public.area_acceptances "
            "where area_id = $1 and user_id = $2)",
            incident_id,
            user.id,
        )
        if not already:
            is_first = not await conn.fetchval(
                "select exists (select 1 from public.area_acceptances "
                "where area_id = $1 and is_first)",
                incident_id,
            )
            if is_first:
                # reported -> verified -> en_route, both hops validated, both
                # stamped by the lifecycle trigger on the way past.
                assert_transition(current, "verified")
                await conn.execute(
                    "update public.areas set status = 'verified', verified_by = $2 "
                    "where id = $1",
                    incident_id,
                    user.id,
                )
                assert_transition("verified", "en_route")
                await conn.execute(
                    "update public.areas set status = 'en_route' where id = $1",
                    incident_id,
                )
                moved = True
            await conn.execute(
                """
                insert into public.area_acceptances
                    (area_id, user_id, agency, organization_id, is_first)
                values ($1, $2, $3::public.agency_type, $4, $5)
                """,
                incident_id,
                user.id,
                user.agency_type,
                user.primary_org_id,
                is_first,
            )
            if moved:
                await _audit_transition(
                    conn, request, user, incident_id,
                    action="incident.accept", before=current, after="en_route",
                    metadata={"agency": user.agency_type, "first_accept": True},
                )
            else:
                await record_audit(
                    conn,
                    request,
                    user,
                    action="incident.accept.participate",
                    entity_type="area",
                    entity_id=incident_id,
                    area_id=incident_id,
                    metadata={
                        "agency": user.agency_type,
                        "first_accept": False,
                        "status_at_accept": current,
                    },
                )
    log.info(
        "incident_accepted",
        incident_id=str(incident_id),
        user_id=str(user.id),
        agency=user.agency_type,
        moved_status=moved,
    )
    return await finish_incident_change(db, incident_id, "incident_accepted")


# --------------------------------------------------------------------------- #
# Dispatch (Section 9 — manual + self-select)
# --------------------------------------------------------------------------- #
@router.get(
    "/{incident_id}/available-responders",
    response_model=list[AvailableResponder],
    summary="List response_team users a sub-admin can dispatch (crew picker)",
)
async def list_available_responders(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> list[AvailableResponder]:
    """Response_team users for the manual-dispatch picker (agency-scoped; admin sees all)."""
    assert_coordinator(user, "dispatch responders")
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)

    params: list[Any] = [incident_id]
    agency_filter = ""
    if user.role == "sub_admin" and user.agency_type is not None:
        params.append(user.agency_type)
        agency_filter = f"and u.agency_type = ${len(params)}::public.agency_type"

    rows = await db.fetch(
        f"""
        select u.id, u.full_name, u.agency_type::text as agency_type,
               u.primary_org_id as organization_id,
               exists(
                   select 1 from public.dispatch_logs d
                   where d.responder_id = u.id and d.status = 'active'
               ) as is_busy,
               exists(
                   select 1 from public.dispatch_logs d
                   where d.responder_id = u.id and d.status = 'active' and d.area_id = $1
               ) as on_this_incident
        from public.users u
        where u.role = 'response_team' {agency_filter}
        order by u.full_name nulls last
        """,
        *params,
    )
    return [AvailableResponder.model_validate(dict(r)) for r in rows]


def _assert_attachable(current: str) -> None:
    """Raise 409 unless a responder may attach to an incident in ``current`` status."""
    if current in _RESPONDER_ATTACHABLE:
        return
    raise ConflictError(
        f"Cannot join an incident in '{current}' status; someone must accept it first.",
        details={"current_status": current, "allowed_when": list(_RESPONDER_ATTACHABLE)},
    )


# v11 removed manual dispatch (Section 2.5). Choosing a truck and a crew while
# an incident was live was the largest source of paperwork during the response;
# that record now belongs to the Post-Incident Report, filed afterwards from
# memory of the scene. Responders self-select below instead.


@router.post(
    "/{incident_id}/self-dispatch",
    response_model=IncidentDetail,
    summary="Self-select onto an incident (response_team)",
)
async def self_dispatch(
    incident_id: UUID,
    payload: SelfDispatchRequest,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """A response_team member adds themselves to an accepted incident (self-select).

    v11: this attaches a responder to the incident and nothing more. It is what
    makes their GPS fixes acceptable and the Arrived button theirs to press — the
    status was already moved by whoever pressed Accept, so nothing here changes
    it. The roster of who actually went is captured afterwards, on the
    Post-Incident Report (Section 2.5.3).
    """
    if user.role != "response_team":
        raise ForbiddenError("Only response_team members may self-select onto incidents.")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    _assert_attachable(current)

    if await _active_dispatch_id(db, incident_id, user.id):
        raise ConflictError("You have already joined this incident.")

    org_id = payload.organization_id or user.primary_org_id
    async with db.acquire() as conn, conn.transaction():
        current = await _lock_status(conn, incident_id)
        _assert_attachable(current)
        dispatch_id = await conn.fetchval(
            """
            insert into public.dispatch_logs
                (area_id, responder_id, organization_id, dispatch_type, dispatched_by,
                 status, notes)
            values ($1, $2, $3, 'self_select', null, 'active', $4)
            returning id
            """,
            incident_id,
            user.id,
            org_id,
            payload.notes,
        )
        await record_audit(
            conn,
            request,
            user,
            action="incident.self_dispatch",
            entity_type="area",
            entity_id=incident_id,
            area_id=incident_id,
            metadata={
                "dispatch_id": str(dispatch_id),
                "organization_id": str(org_id) if org_id else None,
                "status_at_join": current,
            },
        )
    log.info(
        "responder_self_dispatched",
        incident_id=str(incident_id),
        responder_id=str(user.id),
    )
    return await finish_incident_change(db, incident_id, "responder_dispatched")


@router.get(
    "/{incident_id}/dispatches",
    response_model=list[DispatchItem],
    summary="List dispatches for an incident",
)
async def list_dispatches(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> list[DispatchItem]:
    """List every dispatch (active/withdrawn/completed) assigned to an incident."""
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    rows = await db.fetch(
        """
        select d.id, d.area_id, d.responder_id, u.full_name as responder_name,
               d.organization_id, d.dispatch_type::text as dispatch_type, d.dispatched_by,
               d.status::text as status, d.dispatched_at, d.withdrawn_at, d.completed_at,
               d.vehicle_name, d.crew_role, d.notes
        from public.dispatch_logs d
        left join public.users u on u.id = d.responder_id
        where d.area_id = $1
        order by d.dispatched_at asc
        """,
        incident_id,
    )
    return [DispatchItem.model_validate(dict(r)) for r in rows]


# v11 removed Withdraw along with manual dispatch (Section 2.5): there is no
# assignment to take back any more. A responder who is no longer coming simply
# does not appear on the Post-Incident Report roster.


# --------------------------------------------------------------------------- #
# Response progression (Section 9 — responder self-advance)
# --------------------------------------------------------------------------- #
# v11 has no /en-route: the first Accept carries the incident through verified
# into en_route in one transaction (Section 2.5.1), so responders are already
# rolling by the time they open the incident. Arrived is the next thing they
# press.


@router.post(
    "/{incident_id}/arrived",
    response_model=IncidentDetail,
    summary="Mark responders arrived on scene",
)
async def mark_arrived(
    incident_id: UUID, request: Request, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Advance an en_route incident to arrived (assigned responder or sub-admin)."""
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    await _assert_responder_or_coordinator(db, incident_id, user)
    assert_transition(current, "arrived")
    async with db.acquire() as conn, conn.transaction():
        current = await _lock_status(conn, incident_id)
        assert_transition(current, "arrived")
        await conn.execute(
            "update public.areas set status = 'arrived' where id = $1", incident_id
        )
        await _audit_transition(
            conn, request, user, incident_id,
            action="incident.arrived", before=current, after="arrived",
        )
    log.info("incident_arrived", incident_id=str(incident_id), user_id=str(user.id))
    return await finish_incident_change(db, incident_id, "incident_arrived")


# --------------------------------------------------------------------------- #
# Responder GPS stream (Section 8 — 5 s cadence; mirrors the WS 'location' frame)
# --------------------------------------------------------------------------- #
@router.post(
    "/{incident_id}/location",
    response_model=MessageResponse,
    summary="Post a responder GPS fix (5 s cadence)",
)
async def post_responder_location(
    incident_id: UUID,
    payload: ResponderLocationCreate,
    user: StaffUser,
    db: DatabaseDep,
) -> MessageResponse:
    """Append one GPS fix from the calling responder and broadcast it to subscribers."""
    if user.role != "response_team":
        raise ForbiddenError("Only response_team responders may stream their location.")
    recorded = await record_responder_location(db, incident_id, user.id, payload)
    if not recorded:
        await _load_status(db, incident_id)  # 404 if the incident does not exist
        raise ForbiddenError("You have no active dispatch to this incident.")
    await broadcast_responder_location(
        incident_id,
        user.id,
        {
            "lat": payload.lat,
            "lng": payload.lng,
            "accuracy_m": payload.accuracy_m,
            "speed_mps": payload.speed_mps,
            "heading_deg": payload.heading_deg,
            "captured_at": payload.captured_at.isoformat(),
        },
    )
    log.info(
        "responder_location_posted",
        incident_id=str(incident_id),
        responder_id=str(user.id),
    )
    return MessageResponse(message="Location recorded.")

@router.get(
    "/{incident_id}/responders/locations",
    response_model=list[ResponderLocationItem],
    summary="Latest known location per responder",
)
async def list_responder_locations(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> list[ResponderLocationItem]:
    """Return the most recent GPS fix for each responder on the incident (live map)."""
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    rows = await db.fetch(
        """
        select distinct on (responder_id)
               responder_id, lat, lng, accuracy_m, speed_mps, heading_deg,
               captured_at, created_at, dispatch_id
        from public.responder_locations
        where area_id = $1
        order by responder_id, captured_at desc
        """,
        incident_id,
    )
    return [ResponderLocationItem.model_validate(dict(r)) for r in rows]