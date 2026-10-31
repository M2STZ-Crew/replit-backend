"""Area (incident cluster) read endpoints (Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.area import (
    AreaAgenciesResponse,
    AreaDetail,
    AreaOverlapItem,
    AreaSummary,
    RequestAgenciesRequest,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.common import MessageResponse
from app.schemas.tracking import TrackingSnapshot
from app.services.access import DECIDE_OVERLAPS, admin_access
from app.services.audit import record_audit
from app.services.clustering import recompute_area
from app.services.incident import active_area_sql, assert_transition, requested_sql
from app.services.map_feed import AREA_SUMMARY_COLS, publish_area_change
from app.services.tracking import build_tracking_snapshot, can_track

log = get_logger(__name__)

router = APIRouter(prefix="/areas", tags=["areas"])

_VALID_AGENCIES = {"fire_volunteer", "bfp", "barangay", "medical", "police"}


@router.get("", response_model=list[AreaSummary], summary="List incident areas")
async def list_areas(
    user: CurrentUser, db: DatabaseDep, active_only: bool = True
) -> list[AreaSummary]:
    """List areas (active by default: not resolved/rejected/merged)."""
    where = f"where {active_area_sql()}" if active_only else ""
    rows = await db.fetch(
        f"""
        select {AREA_SUMMARY_COLS}
        from public.areas
        {where}
        order by reported_at desc
        limit 200
        """
    )
    return [AreaSummary.model_validate(dict(r)) for r in rows]


@router.get(
    "/{area_id}/tracking",
    response_model=TrackingSnapshot,
    summary="Track It Live: status and responder positions",
)
async def get_tracking(area_id: UUID, user: CurrentUser, db: DatabaseDep) -> TrackingSnapshot:
    """The picture Track It Live draws, for the citizen who reported this incident.

    The same snapshot the ``track:<area_id>`` socket channel pushes. The app reads
    it once on open, then follows the socket, and falls back to polling this when
    the socket is down. Staff who can see the incident may read it too.
    """
    if not await can_track(db, user, area_id):
        raise ForbiddenError("You can follow live tracking only for an incident you reported.")
    snapshot = await build_tracking_snapshot(db, area_id)
    if snapshot is None:
        raise NotFoundError("Incident not found.")
    return snapshot


@router.get("/{area_id}", response_model=AreaDetail, summary="Get an area with its reports")
async def get_area(area_id: UUID, user: CurrentUser, db: DatabaseDep) -> AreaDetail:
    """Return one area with confidence components and its member reports."""
    area = await db.fetchrow(
        """
        select id, designation, status::text as status, centroid_lat, centroid_lng,
               report_count, confidence_score, confidence_band::text as confidence_band,
               alarm_level::text as alarm_level, reported_at, updated_at,
               n_score, s_score, v_score, parent_area_id, version
        from public.areas
        where id = $1
        """,
        area_id,
    )
    if area is None:
        raise NotFoundError("Area not found.")
    reports = await db.fetch(
        """
        select r.id, r.device_lat, r.device_lng, r.has_exif, r.gps_discrepancy_flag,
               r.user_verified_percent, r.created_at
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        where ar.area_id = $1
        order by r.created_at asc
        """,
        area_id,
    )
    data = dict(area)
    data["reports"] = [dict(r) for r in reports]
    return AreaDetail.model_validate(data)


@router.post(
    "/{area_id}/request-agencies",
    response_model=AreaAgenciesResponse,
    summary="Add responder agencies to your incident",
)
async def request_area_agencies(
    area_id: UUID,
    payload: RequestAgenciesRequest,
    user: CurrentUser,
    db: DatabaseDep,
) -> AreaAgenciesResponse:
    """Append agencies to the caller's own report(s) in this area (no new report)."""
    invalid = [a for a in payload.agencies if a not in _VALID_AGENCIES]
    if invalid:
        raise BadRequestError(f"Invalid agency selection: {', '.join(invalid)}.")

    rows = await db.fetch(
        """
        select r.id, r.selected_agencies
        from public.reports r
        join public.area_reports ar on ar.report_id = r.id
        where ar.area_id = $1 and r.reporter_id = $2
        """,
        area_id,
        user.id,
    )
    if not rows:
        raise NotFoundError("You have no report in this incident.")

    merged_all: set[str] = set()
    for row in rows:
        current = list(row["selected_agencies"] or [])
        merged = sorted(set(current) | set(payload.agencies))
        await db.execute(
            "update public.reports set selected_agencies = $2::public.agency_type[] "
            "where id = $1",
            row["id"],
            merged,
        )
        merged_all.update(merged)

    log.info(
        "area_agencies_added", area_id=str(area_id), user_id=str(user.id),
        added=payload.agencies,
    )
    return AreaAgenciesResponse(
        area_id=area_id,
        agencies=sorted(merged_all),
        message="Responder agencies added to your incident.",
    )

@router.get(
    "/overlaps/pending",
    response_model=list[AreaOverlapItem],
    summary="List pending area overlaps (dispatcher)",
)
async def list_pending_overlaps(staff: StaffUser, db: DatabaseDep) -> list[AreaOverlapItem]:
    """List undecided overlaps still within the 120 s decision window.

    An organisation's Admin is shown only the overlaps it may decide: both
    Areas routed to it (pass 6 A00, A27).
    """
    conditions = ["o.decision is null", "o.expires_at > now()"]
    params: list[object] = []
    access = admin_access(staff)
    if access is not None and access.act_agencies is not None:
        if not access.can(DECIDE_OVERLAPS) or not access.act_agencies:
            return []
        params.append(list(access.act_agencies))
        conditions.append(requested_sql("o.area_a_id", 1))
        conditions.append(requested_sql("o.area_b_id", 1))
    rows = await db.fetch(
        f"""
        select o.id, o.area_a_id, o.area_b_id,
               a.designation as area_a_designation, b.designation as area_b_designation,
               o.distance_m, o.expires_at, o.created_at
        from public.area_overlaps o
        join public.areas a on a.id = o.area_a_id
        join public.areas b on b.id = o.area_b_id
        where {' and '.join(conditions)}
        order by o.created_at asc
        """,
        *params,
    )
    return [AreaOverlapItem.model_validate(dict(r)) for r in rows]


async def _assert_may_decide_overlap(
    db: Database, overlap_id: UUID, staff: AuthenticatedUser
) -> None:
    """Raise 403 unless an organisation's Admin was routed both Areas.

    Coordinators and the system Admin decide as before. Which Admin decides an
    overlap is still open (pass 6 Q12); until it is settled the console's
    assumption holds: the Admin of an organisation both Areas asked for.
    """
    access = admin_access(staff)
    if access is None or access.act_agencies is None:
        return
    allowed = (
        access.can(DECIDE_OVERLAPS)
        and bool(access.act_agencies)
        and await db.fetchval(
            f"""
            select {requested_sql("o.area_a_id", 2)} and {requested_sql("o.area_b_id", 2)}
            from public.area_overlaps o where o.id = $1
            """,
            overlap_id,
            list(access.act_agencies),
        )
    )
    if not allowed:
        raise ForbiddenError(
            "You can merge or keep apart only Areas that were both routed to your "
            "organization."
        )


@router.post(
    "/overlaps/{overlap_id}/keep-separate",
    response_model=MessageResponse,
    summary="Keep two overlapping areas separate",
)
async def keep_areas_separate(
    overlap_id: UUID, request: Request, staff: StaffUser, db: DatabaseDep
) -> MessageResponse:
    """Record an explicit Keep-Separate decision (the 120 s default outcome)."""
    await _assert_may_decide_overlap(db, overlap_id, staff)
    kept = await db.fetchrow(
        """
        update public.area_overlaps
           set decision = 'keep_separate', decided_by = $2, decided_at = now()
         where id = $1 and decision is null
        returning area_a_id, area_b_id
        """,
        overlap_id,
        staff.id,
    )
    if kept is None:
        raise NotFoundError("No pending overlap found for that id.")
    # On the newer Area, which is the one the decision was about. A
    # coordinator's "My decisions" reads these rows back (GET /audit-logs).
    await record_audit(
        db,
        request,
        staff,
        action="area.keep_separate",
        entity_type="area_overlap",
        entity_id=overlap_id,
        area_id=kept["area_b_id"],
        metadata={"other_area_id": str(kept["area_a_id"])},
    )
    log.info("overlap_kept_separate", overlap_id=str(overlap_id), staff_id=str(staff.id))
    return MessageResponse(message="Areas kept separate.")


@router.post(
    "/overlaps/{overlap_id}/merge",
    response_model=MessageResponse,
    summary="Merge two overlapping areas",
)
async def merge_areas(
    overlap_id: UUID, request: Request, staff: StaffUser, db: DatabaseDep
) -> MessageResponse:
    """Merge area B into area A: move reports, recompute A, mark B merged (120 s window)."""
    await _assert_may_decide_overlap(db, overlap_id, staff)
    overlap = await db.fetchrow(
        "select area_a_id, area_b_id, decision, expires_at from public.area_overlaps where id = $1",
        overlap_id,
    )
    if overlap is None:
        raise NotFoundError("Overlap not found.")
    if overlap["decision"] is not None:
        raise BadRequestError("This overlap was already decided.")
    if overlap["expires_at"] < datetime.now(UTC):
        raise BadRequestError("Decision window expired; the areas default to Keep Separate.")

    keep_id = overlap["area_a_id"]
    drop_id = overlap["area_b_id"]

    # Merging is only legal before responders are committed — after dispatch it
    # would orphan their assignments. 409 rather than silently absorbing.
    drop_status = await db.fetchval(
        "select status::text from public.areas where id = $1", drop_id
    )
    if drop_status is None:
        raise NotFoundError("Area to merge no longer exists.")
    assert_transition(str(drop_status), "merged")

    await db.execute(
        """
        update public.area_reports
           set area_id = $1
         where area_id = $2
           and report_id not in (select report_id from public.area_reports where area_id = $1)
        """,
        keep_id,
        drop_id,
    )
    await db.execute("delete from public.area_reports where area_id = $1", drop_id)
    # 'merged' is its own terminal status (Section 4.1) — recording it as
    # 'rejected' would count every dispatcher merge as a false report.
    await db.execute(
        """
        update public.areas
           set status = 'merged', merged_at = now(), merged_by = $2,
               merged_into_area_id = $3
         where id = $1
        """,
        drop_id,
        staff.id,
        keep_id,
    )
    await db.execute(
        """
        update public.area_overlaps
           set decision = 'merge', decided_by = $2, decided_at = now()
         where id = $1
        """,
        overlap_id,
        staff.id,
    )
    # Filed against the Area that lives on: the merged one has no reports left,
    # so an agency-scoped read of the audit log would never find it there.
    names = await db.fetchrow(
        "select (select designation from public.areas where id = $1) as kept, "
        "(select designation from public.areas where id = $2) as merged",
        keep_id,
        drop_id,
    )
    await record_audit(
        db,
        request,
        staff,
        action="area.merge",
        entity_type="area",
        entity_id=drop_id,
        area_id=keep_id,
        metadata={
            "overlap_id": str(overlap_id),
            "merged_area_id": str(drop_id),
            "merged_designation": names.get("merged") if names else None,
            "kept_designation": names.get("kept") if names else None,
        },
    )
    await recompute_area(db, keep_id)
    await publish_area_change(db, keep_id)
    await publish_area_change(db, drop_id)
    log.info("overlap_merged", keep=str(keep_id), dropped=str(drop_id), staff_id=str(staff.id))
    return MessageResponse(message="Areas merged.")