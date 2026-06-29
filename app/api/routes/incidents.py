"""Incident lifecycle endpoints (Phase 9-10, Sections 8-10).

The operational console over public.areas: a visibility-filtered feed, the
status-transition actions, the dispatch / response progression, and the live
responder GPS stream. Every state-changing action broadcasts to WebSocket
subscribers via app.realtime.events. Visibility is two-way between BFP and Fire
Volunteer; other agencies see only incidents whose member reports selected them;
admin sees everything.

Authority (Section 6 + the chosen coordinator/responder model):
  - verify ................ Fire Volunteer sub-admin only (DB-pinned by trigger)
  - reject / resolve ...... sub-admin (or admin)
  - dispatch (manual) ..... sub-admin (or admin) assigns a response_team user
  - self-dispatch ......... a response_team user selects themselves
  - en_route / arrived .... the assigned responder, or a sub-admin / admin
  - location stream ....... the assigned responder (response_team) only
The matching *_at timestamp is stamped by a database trigger on each status change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DatabaseDep, StaffUser, StorageClientDep
from app.core.exceptions import (
    BadRequestError,
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
    ManualDispatchRequest,
    ResponderLocationCreate,
    ResponderLocationItem,
    SelfDispatchRequest,
)
from app.services.incident import (
    assert_transition,
    record_responder_location,
    visible_agencies,
)
from app.services.incident_notify import (
    notify_incident_reporters,
    notify_responder_dispatched,
)

log = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

# Incident statuses during which new dispatches may be added.
_DISPATCHABLE = ("verified", "dispatched", "en_route", "arrived")


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
    """Allow a sub-admin/admin, or a response_team user with an active dispatch here."""
    if user.role in ("sub_admin", "admin"):
        return
    if user.role == "response_team" and await _active_dispatch_id(db, incident_id, user.id):
        return
    raise ForbiddenError(
        "Only an assigned responder or a sub-admin may advance the response."
    )


async def _build_detail(db: Database, incident_id: UUID) -> IncidentDetail:
    """Build the full IncidentDetail for an incident (assumes existence already checked)."""
    row = await db.fetchrow(
        """
        select a.id, a.designation, a.status::text as status,
               a.centroid_lat, a.centroid_lng, a.report_count,
               a.confidence_score, a.confidence_band::text as confidence_band,
               a.alarm_level::text as alarm_level,
               (select count(*) from public.dispatch_logs d
                where d.area_id = a.id and d.status = 'active') as active_dispatch_count,
               a.reported_at, a.verified_at, a.dispatched_at, a.en_route_at,
               a.arrived_at, a.resolved_at, a.rejected_at, a.updated_at,
               a.n_score, a.s_score, a.v_score, a.version, a.parent_area_id,
               a.verified_by, vu.full_name as verified_by_name,
               a.resolved_by, ru.full_name as resolved_by_name,
               a.rejected_by, ju.full_name as rejected_by_name,
               a.rejection_reason,
               a.alarm_level_set_by, a.alarm_level_set_at
        from public.areas a
        left join public.users vu on vu.id = a.verified_by
        left join public.users ru on ru.id = a.resolved_by
        left join public.users ju on ju.id = a.rejected_by
        where a.id = $1
        """,
        incident_id,
    )
    if row is None:
        raise NotFoundError("Incident not found.")
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
    data["reports"] = [dict(r) for r in reports]
    return IncidentDetail.model_validate(data)


async def _finish(db: Database, incident_id: UUID, event_type: str) -> IncidentDetail:
    """Rebuild the detail, broadcast to subscribers, push the reporter, and return it."""
    detail = await _build_detail(db, incident_id)
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
        conditions.append("a.status not in ('resolved', 'rejected')")
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
        select a.id, a.designation, a.status::text as status,
               a.centroid_lat, a.centroid_lng, a.report_count,
               a.confidence_score, a.confidence_band::text as confidence_band,
               a.alarm_level::text as alarm_level,
               (select count(*) from public.dispatch_logs d
                where d.area_id = a.id and d.status = 'active') as active_dispatch_count,
               a.reported_at, a.verified_at, a.dispatched_at, a.en_route_at,
               a.arrived_at, a.resolved_at, a.rejected_at, a.updated_at
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
            "select count(*) from public.areas where status not in ('resolved', 'rejected')"
        )
        pending = await db.fetchval(
            "select count(*) from public.areas where status = 'pending'"
        )
    elif not agencies:
        active = 0
        pending = 0
    else:
        visible = (
            "exists (select 1 from public.area_reports ar "
            "join public.reports r on r.id = ar.report_id "
            "where ar.area_id = a.id and r.selected_agencies && $1::public.agency_type[])"
        )
        active = await db.fetchval(
            f"select count(*) from public.areas a "
            f"where a.status not in ('resolved', 'rejected') and {visible}",
            agencies,
        )
        pending = await db.fetchval(
            f"select count(*) from public.areas a where a.status = 'pending' and {visible}",
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
    return await _build_detail(db, incident_id)


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
# Lifecycle decision transitions (Section 9)
# --------------------------------------------------------------------------- #
@router.post(
    "/{incident_id}/verify",
    response_model=IncidentDetail,
    summary="Verify an incident (Fire-Volunteer sub-admin only)",
)
async def verify_incident(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Mark an incident verified. DB-pinned to a Fire Volunteer sub-admin (Section 6)."""
    if not (user.role == "sub_admin" and user.agency_type == "fire_volunteer"):
        raise ForbiddenError(
            "Only a Fire Volunteer sub-admin may verify incidents (Section 6)."
        )
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    assert_transition(current, "verified")
    await db.execute(
        "update public.areas set status = 'verified', verified_by = $2 where id = $1",
        incident_id,
        user.id,
    )
    log.info("incident_verified", incident_id=str(incident_id), user_id=str(user.id))
    return await _finish(db, incident_id, "incident_verified")


@router.post(
    "/{incident_id}/reject",
    response_model=IncidentDetail,
    summary="Reject an incident as a false report (sub-admin)",
)
async def reject_incident(
    incident_id: UUID,
    payload: IncidentRejectRequest,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """Reject an incident (invalid / false report). Sub-admins of the agency, or admin."""
    if user.role not in ("sub_admin", "admin"):
        raise ForbiddenError("Only a sub-admin may reject incidents.")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    assert_transition(current, "rejected")
    await db.execute(
        """
        update public.areas
           set status = 'rejected', rejected_by = $2, rejection_reason = $3
         where id = $1
        """,
        incident_id,
        user.id,
        payload.reason,
    )
    log.info("incident_rejected", incident_id=str(incident_id), user_id=str(user.id))
    return await _finish(db, incident_id, "incident_rejected")


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentDetail,
    summary="Resolve an incident / fire out (sub-admin)",
)
async def resolve_incident(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Resolve an incident (fire out). Completes any still-active dispatches."""
    if user.role not in ("sub_admin", "admin"):
        raise ForbiddenError("Only a sub-admin may resolve incidents.")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    assert_transition(current, "resolved")
    await db.execute(
        "update public.areas set status = 'resolved', resolved_by = $2 where id = $1",
        incident_id,
        user.id,
    )
    await db.execute(
        """
        update public.dispatch_logs
           set status = 'completed', completed_at = now()
         where area_id = $1 and status = 'active'
        """,
        incident_id,
    )
    log.info("incident_resolved", incident_id=str(incident_id), user_id=str(user.id))
    return await _finish(db, incident_id, "incident_resolved")


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
    if user.role not in ("sub_admin", "admin"):
        raise ForbiddenError("Only a sub-admin may view dispatchable responders.")
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


@router.post(
    "/{incident_id}/dispatch",
    response_model=IncidentDetail,
    summary="Dispatch a response_team member (manual, sub-admin)",
)
async def dispatch_responder(
    incident_id: UUID,
    payload: ManualDispatchRequest,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """Sub-admin assigns a response_team user to a verified incident (manual dispatch)."""
    if user.role not in ("sub_admin", "admin"):
        raise ForbiddenError("Only a sub-admin may dispatch responders.")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    if current not in _DISPATCHABLE:
        raise ConflictError(
            f"Cannot dispatch to an incident in '{current}' status; verify it first.",
            details={"current_status": current, "allowed_when": list(_DISPATCHABLE)},
        )

    responder = await db.fetchrow(
        "select role::text as role, primary_org_id from public.users where id = $1",
        payload.responder_id,
    )
    if responder is None:
        raise NotFoundError("Responder not found.")
    if responder["role"] != "response_team":
        raise BadRequestError("Only response_team users can be dispatched.")

    if await _active_dispatch_id(db, incident_id, payload.responder_id):
        raise ConflictError("That responder already has an active dispatch to this incident.")

    org_id = payload.organization_id or responder["primary_org_id"]
    await db.execute(
        """
        insert into public.dispatch_logs
            (area_id, responder_id, organization_id, dispatch_type, dispatched_by,
             status, vehicle_name, crew_role, notes)
        values ($1, $2, $3, 'manual', $4, 'active', $5, $6, $7)
        """,
        incident_id,
        payload.responder_id,
        org_id,
        user.id,
        payload.vehicle_name,
        payload.crew_role,
        payload.notes,
    )
    if current == "verified":
        await db.execute(
            "update public.areas set status = 'dispatched' where id = $1", incident_id
        )
    log.info(
        "responder_dispatched",
        incident_id=str(incident_id),
        responder_id=str(payload.responder_id),
        by=str(user.id),
    )
    try:
        await notify_responder_dispatched(
            db,
            payload.responder_id,
            incident_id,
            vehicle_name=payload.vehicle_name,
            crew_role=payload.crew_role,
        )
    except Exception:
        log.error(
            "responder_dispatch_notify_failed", incident_id=str(incident_id), exc_info=True
        )
    return await _finish(db, incident_id, "responder_dispatched")


@router.post(
    "/{incident_id}/self-dispatch",
    response_model=IncidentDetail,
    summary="Self-select onto an incident (response_team)",
)
async def self_dispatch(
    incident_id: UUID,
    payload: SelfDispatchRequest,
    user: StaffUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """A response_team member adds themselves to a verified incident (self-select)."""
    if user.role != "response_team":
        raise ForbiddenError("Only response_team members may self-select onto incidents.")
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    if current not in _DISPATCHABLE:
        raise ConflictError(
            f"Cannot self-dispatch to an incident in '{current}' status; "
            "it must be verified first.",
            details={"current_status": current, "allowed_when": list(_DISPATCHABLE)},
        )

    if await _active_dispatch_id(db, incident_id, user.id):
        raise ConflictError("You already have an active dispatch to this incident.")

    org_id = payload.organization_id or user.primary_org_id
    await db.execute(
        """
        insert into public.dispatch_logs
            (area_id, responder_id, organization_id, dispatch_type, dispatched_by,
             status, notes)
        values ($1, $2, $3, 'self_select', null, 'active', $4)
        """,
        incident_id,
        user.id,
        org_id,
        payload.notes,
    )
    if current == "verified":
        await db.execute(
            "update public.areas set status = 'dispatched' where id = $1", incident_id
        )
    log.info(
        "responder_self_dispatched",
        incident_id=str(incident_id),
        responder_id=str(user.id),
    )
    return await _finish(db, incident_id, "responder_dispatched")


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


@router.post(
    "/{incident_id}/dispatches/{dispatch_id}/withdraw",
    response_model=IncidentDetail,
    summary="Withdraw a dispatch",
)
async def withdraw_dispatch(
    incident_id: UUID, dispatch_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Withdraw a dispatch. The responder may withdraw themselves; sub-admin/admin anyone."""
    await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    dispatch = await db.fetchrow(
        """
        select responder_id, status::text as status
        from public.dispatch_logs
        where id = $1 and area_id = $2
        """,
        dispatch_id,
        incident_id,
    )
    if dispatch is None:
        raise NotFoundError("Dispatch not found for this incident.")
    is_owner = dispatch["responder_id"] == user.id
    if not (is_owner or user.role in ("sub_admin", "admin")):
        raise ForbiddenError("You may only withdraw your own dispatch.")
    if dispatch["status"] != "active":
        raise ConflictError("That dispatch is not active.")
    await db.execute(
        """
        update public.dispatch_logs
           set status = 'withdrawn', withdrawn_at = now()
         where id = $1
        """,
        dispatch_id,
    )
    log.info(
        "dispatch_withdrawn",
        incident_id=str(incident_id),
        dispatch_id=str(dispatch_id),
        by=str(user.id),
    )
    return await _finish(db, incident_id, "dispatch_withdrawn")


# --------------------------------------------------------------------------- #
# Response progression (Section 9 — responder self-advance)
# --------------------------------------------------------------------------- #
@router.post(
    "/{incident_id}/en-route",
    response_model=IncidentDetail,
    summary="Mark responders en route",
)
async def mark_en_route(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Advance a dispatched incident to en_route (assigned responder or sub-admin)."""
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    await _assert_responder_or_coordinator(db, incident_id, user)
    assert_transition(current, "en_route")
    await db.execute(
        "update public.areas set status = 'en_route' where id = $1", incident_id
    )
    log.info("incident_en_route", incident_id=str(incident_id), user_id=str(user.id))
    return await _finish(db, incident_id, "incident_en_route")


@router.post(
    "/{incident_id}/arrived",
    response_model=IncidentDetail,
    summary="Mark responders arrived on scene",
)
async def mark_arrived(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Advance an en_route incident to arrived (assigned responder or sub-admin)."""
    current = await _load_status(db, incident_id)
    await _assert_visible(db, incident_id, user)
    await _assert_responder_or_coordinator(db, incident_id, user)
    assert_transition(current, "arrived")
    await db.execute(
        "update public.areas set status = 'arrived' where id = $1", incident_id
    )
    log.info("incident_arrived", incident_id=str(incident_id), user_id=str(user.id))
    return await _finish(db, incident_id, "incident_arrived")


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