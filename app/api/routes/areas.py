"""Area (incident cluster) read endpoints (Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.schemas.area import AreaDetail, AreaOverlapItem, AreaSummary
from app.schemas.common import MessageResponse
from app.services.clustering import recompute_area

log = get_logger(__name__)

router = APIRouter(prefix="/areas", tags=["areas"])


@router.get("", response_model=list[AreaSummary], summary="List incident areas")
async def list_areas(
    user: CurrentUser, db: DatabaseDep, active_only: bool = True
) -> list[AreaSummary]:
    """List areas (active by default: not resolved/rejected)."""
    where = "where status not in ('resolved', 'rejected')" if active_only else ""
    rows = await db.fetch(
        f"""
        select id, designation, status::text as status, centroid_lat, centroid_lng,
               report_count, confidence_score, confidence_band::text as confidence_band,
               alarm_level::text as alarm_level, reported_at, updated_at
        from public.areas
        {where}
        order by reported_at desc
        limit 200
        """
    )
    return [AreaSummary.model_validate(dict(r)) for r in rows]


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

@router.get(
    "/overlaps/pending",
    response_model=list[AreaOverlapItem],
    summary="List pending area overlaps (dispatcher)",
)
async def list_pending_overlaps(staff: StaffUser, db: DatabaseDep) -> list[AreaOverlapItem]:
    """List undecided overlaps still within the 120 s decision window."""
    rows = await db.fetch(
        """
        select o.id, o.area_a_id, o.area_b_id,
               a.designation as area_a_designation, b.designation as area_b_designation,
               o.distance_m, o.expires_at, o.created_at
        from public.area_overlaps o
        join public.areas a on a.id = o.area_a_id
        join public.areas b on b.id = o.area_b_id
        where o.decision is null and o.expires_at > now()
        order by o.created_at asc
        """
    )
    return [AreaOverlapItem.model_validate(dict(r)) for r in rows]


@router.post(
    "/overlaps/{overlap_id}/keep-separate",
    response_model=MessageResponse,
    summary="Keep two overlapping areas separate",
)
async def keep_areas_separate(
    overlap_id: UUID, staff: StaffUser, db: DatabaseDep
) -> MessageResponse:
    """Record an explicit Keep-Separate decision (the 120 s default outcome)."""
    result = await db.execute(
        """
        update public.area_overlaps
           set decision = 'keep_separate', decided_by = $2, decided_at = now()
         where id = $1 and decision is null
        """,
        overlap_id,
        staff.id,
    )
    if result.endswith(" 0"):
        raise NotFoundError("No pending overlap found for that id.")
    log.info("overlap_kept_separate", overlap_id=str(overlap_id), staff_id=str(staff.id))
    return MessageResponse(message="Areas kept separate.")


@router.post(
    "/overlaps/{overlap_id}/merge",
    response_model=MessageResponse,
    summary="Merge two overlapping areas",
)
async def merge_areas(overlap_id: UUID, staff: StaffUser, db: DatabaseDep) -> MessageResponse:
    """Merge area B into area A: move reports, recompute A, reject B (120 s window)."""
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
    await db.execute(
        """
        update public.areas
           set status = 'rejected', rejected_at = now(), rejected_by = $2,
               rejection_reason = 'merged'
         where id = $1
        """,
        drop_id,
        staff.id,
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
    await recompute_area(db, keep_id)
    log.info("overlap_merged", keep=str(keep_id), dropped=str(drop_id), staff_id=str(staff.id))
    return MessageResponse(message="Areas merged.")