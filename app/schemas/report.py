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
    """A citizen's own report, with signed media URLs."""

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