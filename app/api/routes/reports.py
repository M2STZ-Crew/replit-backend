"""Incident reporting API (Phase 6).

POST /reports/submit: multipart SOS submission — photo (<=5MB JPEG/PNG) + optional
video (<=1.5MB MP4), device GPS, compass bearing (metadata only), multi-agency
selection. Extracts EXIF GPS and cross-references it against the device GPS at a
100 m threshold (Section 3.1), uploads media to Supabase Storage, and persists the
report. Area clustering (Phase 7) consumes these rows.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CurrentUser, DatabaseDep, StorageClientDep
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.logging import get_logger
from app.integrations.fcm import PushService
from app.schemas.report import ReportResponse, ReportSubmitResponse
from app.services.clustering import cluster_report
from app.services.exif import extract_gps, validate_image
from app.services.geo import haversine_m
from app.workers.neighborhood import notify_area_neighbors

log = get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

_VALID_AGENCIES = {"fire_volunteer", "bfp", "barangay", "medical", "police"}


def _parse_agencies(raw: str) -> list[str]:
    """Parse + validate a comma-separated agency list against agency_type values."""
    agencies = [a.strip() for a in raw.split(",") if a.strip()]
    invalid = [a for a in agencies if a not in _VALID_AGENCIES]
    if invalid:
        raise BadRequestError(f"Invalid agency selection: {', '.join(invalid)}.")
    return agencies

async def _sign_or_none(
    storage: StorageClientDep, bucket: str, path: str | None
) -> str | None:
    """Sign a private object, returning None (not a 502) when it can't be signed.

    A deleted/missing object makes Supabase return 400 on sign; without this, one
    orphaned report would break the entire /reports/mine listing.
    """
    if not path:
        return None
    try:
        return await storage.create_signed_url(bucket=bucket, path=path)
    except ExternalServiceError:
        log.warning("report_media_unsigned", bucket=bucket, path=path)
        return None

@router.post(
    "/submit",
    response_model=ReportSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an incident report (SOS)",
)
async def submit_report(
    user: CurrentUser,
    db: DatabaseDep,
    storage: StorageClientDep,
    device_lat: Annotated[float, Form(ge=-90, le=90)],
    device_lng: Annotated[float, Form(ge=-180, le=180)],
    photo: Annotated[UploadFile, File(description="Incident photo, JPEG/PNG <=5MB")],
    selected_agencies: Annotated[str, Form(description="Comma-separated agencies")] = "",
    device_gps_accuracy_m: Annotated[float | None, Form()] = None,
    compass_bearing: Annotated[float | None, Form(ge=0, lt=360)] = None,
    notes: Annotated[str | None, Form(max_length=2000)] = None,
    video: Annotated[UploadFile | None, File(description="Optional MP4 <=1.5MB")] = None,
) -> ReportSubmitResponse:
    """Validate, store, EXIF-cross-reference, and persist a citizen incident report."""
    settings = get_settings()
    agencies = _parse_agencies(selected_agencies)

    # --- Photo: validate type, size, and that it's a real image ---
    photo_bytes = await photo.read()
    if photo.content_type not in ("image/jpeg", "image/png"):
        raise BadRequestError("Photo must be JPEG or PNG.")
    if len(photo_bytes) > settings.report_max_photo_bytes:
        raise BadRequestError("Photo exceeds the 5 MB limit.")
    validate_image(photo_bytes)
    photo_ext = ".png" if photo.content_type == "image/png" else ".jpg"

    # --- Optional video: type + size only (resolution/duration are client-enforced) ---
    video_bytes: bytes | None = None
    if video is not None and video.filename:
        video_bytes = await video.read()
        if video.content_type != "video/mp4":
            raise BadRequestError("Video must be MP4.")
        if len(video_bytes) > settings.report_max_video_bytes:
            raise BadRequestError("Video exceeds the 1.5 MB limit.")

    # --- EXIF GPS + device-vs-EXIF cross-reference (Section 3.1) ---
    exif = extract_gps(photo_bytes)
    has_exif = exif is not None
    exif_lat = exif[0] if exif is not None else None
    exif_lng = exif[1] if exif is not None else None
    gps_discrepancy_m: float | None = None
    gps_discrepancy_flag = False
    if exif is not None:
        gps_discrepancy_m = haversine_m(device_lat, device_lng, exif[0], exif[1])
        gps_discrepancy_flag = gps_discrepancy_m > settings.gps_discrepancy_threshold_m

    # --- Upload media to Storage (path: <user_id>/<report_id>.<ext>) ---
    report_id = uuid4()
    photo_path = f"{user.id}/{report_id}{photo_ext}"
    await storage.upload(
        bucket="incident-photos",
        path=photo_path,
        content=photo_bytes,
        content_type=photo.content_type or "image/jpeg",
    )
    video_path: str | None = None
    if video_bytes is not None:
        video_path = f"{user.id}/{report_id}.mp4"
        await storage.upload(
            bucket="incident-videos",
            path=video_path,
            content=video_bytes,
            content_type="video/mp4",
        )

    # --- Persist ---
    row = await db.fetchrow(
        """
        insert into public.reports (
            id, reporter_id, device_lat, device_lng, device_gps_accuracy_m,
            exif_lat, exif_lng, has_exif, gps_discrepancy_m, gps_discrepancy_flag,
            compass_bearing, photo_url, photo_size_bytes, video_url, video_size_bytes,
            selected_agencies, user_verified_percent, notes
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                  $16::public.agency_type[], $17, $18)
        returning id, created_at
        """,
        report_id,
        user.id,
        device_lat,
        device_lng,
        device_gps_accuracy_m,
        exif_lat,
        exif_lng,
        has_exif,
        gps_discrepancy_m,
        gps_discrepancy_flag,
        compass_bearing,
        photo_path,
        len(photo_bytes),
        video_path,
        len(video_bytes) if video_bytes is not None else None,
        agencies,
        user.verified_percent,
        notes,
    )
    
    assert row is not None

    area_id = await cluster_report(db, report_id=report_id, lat=device_lat, lng=device_lng)
    area = await db.fetchrow(
        "select designation, centroid_lat, centroid_lng from public.areas where id = $1",
        area_id,
    )
    assert area is not None

    # Keep the reporter locatable for future incidents, then immediately alert
    # nearby users (300 m) — they don't have to wait for the 60 s worker tick.
    await db.execute(
        "update public.users set latitude = $2, longitude = $3, last_active_at = now() "
        "where id = $1",
        user.id,
        device_lat,
        device_lng,
    )
    # Centre the 300 m query on the area centroid, not this reporter's position
    # (Section 3.5). Clustering has just recomputed the centroid, so for a report
    # joining an existing area the two differ — using the reporter's coordinates
    # would blast a different circle than every subsequent 60 s tick.
    try:
        await notify_area_neighbors(
            db,
            PushService(),
            area_id,
            float(area["centroid_lat"]),
            float(area["centroid_lng"]),
        )
    except Exception:
        log.error("immediate_neighbor_notify_failed", area_id=str(area_id), exc_info=True)

    if not has_exif:
        note = "No EXIF GPS (e.g. gallery upload)."
    elif gps_discrepancy_flag:
        note = "GPS discrepancy flagged for Sub-Admin review."
    else:
        note = "Device and EXIF GPS agree."
    log.info(
        "report_submitted",
        report_id=str(report_id),
        user_id=str(user.id),
        area_id=str(area_id),
        has_exif=has_exif,
        gps_discrepancy_flag=gps_discrepancy_flag,
    )
    return ReportSubmitResponse(
        id=row["id"],
        created_at=row["created_at"],
        has_exif=has_exif,
        gps_discrepancy_m=gps_discrepancy_m,
        gps_discrepancy_flag=gps_discrepancy_flag,
        area_id=area_id,
        area_designation=area["designation"],
        message=f"Report submitted. {note}",
    )


@router.get("/mine", response_model=list[ReportResponse], summary="List my reports")
async def list_my_reports(
    user: CurrentUser, db: DatabaseDep, storage: StorageClientDep
) -> list[ReportResponse]:
    """Return the caller's reports with signed media URLs."""
    rows = await db.fetch(
        """
        select id, device_lat, device_lng, has_exif, gps_discrepancy_m,
               gps_discrepancy_flag, compass_bearing, selected_agencies,
               user_verified_percent, photo_url, video_url, created_at
        from public.reports
        where reporter_id = $1
        order by created_at desc
        limit 100
        """,
        user.id,
    )
    items: list[ReportResponse] = []
    for r in rows:
        items.append(
            ReportResponse(
                id=r["id"],
                device_lat=r["device_lat"],
                device_lng=r["device_lng"],
                has_exif=r["has_exif"],
                gps_discrepancy_m=r["gps_discrepancy_m"],
                gps_discrepancy_flag=r["gps_discrepancy_flag"],
                compass_bearing=r["compass_bearing"],
                selected_agencies=list(r["selected_agencies"]),
                user_verified_percent=r["user_verified_percent"],
                photo_url=await _sign_or_none(storage, "incident-photos", r["photo_url"]),
                video_url=await _sign_or_none(storage, "incident-videos", r["video_url"]),
                created_at=r["created_at"],
            )
        )
    return items