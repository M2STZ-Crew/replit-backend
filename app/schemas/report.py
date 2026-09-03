"""Incident report schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReportSubmitResponse(BaseModel):
    """Returned after a successful report submission."""

    id: UUID
    created_at: datetime
    has_exif: bool
    gps_discrepancy_m: float | None = None
    gps_discrepancy_flag: bool
    area_id: UUID
    area_designation: str
    message: str


class ReportResponse(BaseModel):
    """A citizen's own report, with signed media URLs and its incident's progress.

    Section 2.6 grants the General User tier "submit reports, view status", so the
    clustered area's designation and lifecycle status travel with the report — a
    reporter needs to know whether responders are on the way, not just that the
    upload succeeded. Nullable because clustering is what creates the link.
    """

    id: UUID
    device_lat: float
    device_lng: float
    has_exif: bool
    gps_discrepancy_m: float | None = None
    gps_discrepancy_flag: bool
    compass_bearing: float | None = None
    selected_agencies: list[str] = Field(default_factory=list)
    user_verified_percent: int
    photo_url: str | None = None
    video_url: str | None = None
    created_at: datetime

    area_id: UUID | None = None
    area_designation: str | None = Field(
        default=None, description='Human label from clustering, e.g. "Area 1.2".'
    )
    area_status: str | None = Field(
        default=None, description="Lifecycle status of the clustered incident."
    )
    area_confidence_band: str | None = Field(
        default=None, description="high | medium | low, from the area confidence score."
    )