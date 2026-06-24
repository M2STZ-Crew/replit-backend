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

from app.api.deps import DatabaseDep, StaffUser
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.realtime.events import broadcast_incident_event, broadcast_responder_location
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import MessageResponse
from app.schemas.incident import (
      DispatchItem,
    IncidentDetail,
    IncidentRejectRequest,
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
               a.verified_by, a.resolved_by, a.rejected_by, a.rejection_reason,
               a.alarm_level_set_by, a.alarm_level_set_at
        from public.areas a
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
    """Rebuild the detail, broadcast the event to subscribers, and return it."""
    detail = await _build_detail(db, incident_id)
    await broadcast_incident_event(detail, event_type)
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
             status, notes)
        values ($1, $2, $3, 'manual', $4, 'active', $5)
        """,
        incident_id,
        payload.responder_id,
        org_id,
        user.id,
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
        select id, area_id, responder_id, organization_id,
               dispatch_type::text as dispatch_type, dispatched_by,
               status::text as status, dispatched_at, withdrawn_at, completed_at, notes
        from public.dispatch_logs
        where area_id = $1
        order by dispatched_at asc
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