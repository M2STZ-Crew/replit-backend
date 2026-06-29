"""Area (incident cluster) schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AreaSummary(BaseModel):
    """Compact area for list/map views."""

    id: UUID
    designation: str
    status: str
    centroid_lat: float
    centroid_lng: float
    report_count: int
    confidence_score: float
    confidence_band: str
    alarm_level: str | None = None
    reported_at: datetime
    updated_at: datetime


class AreaReportItem(BaseModel):
    """A report belonging to an area."""

    id: UUID
    device_lat: float
    device_lng: float
    has_exif: bool
    gps_discrepancy_flag: bool
    user_verified_percent: int
    created_at: datetime


class AreaDetail(AreaSummary):
    """Full area with confidence components, versioning, and member reports."""

    n_score: float
    s_score: float
    v_score: float
    parent_area_id: UUID | None = None
    version: int
    reports: list[AreaReportItem] = Field(default_factory=list)

class AreaOverlapItem(BaseModel):
    """A pending overlap awaiting a Merge / Keep-Separate decision."""

    id: UUID
    area_a_id: UUID
    area_b_id: UUID
    area_a_designation: str
    area_b_designation: str
    distance_m: float
    expires_at: datetime
    created_at: datetime


class RequestAgenciesRequest(BaseModel):
    """Citizen request to add responder agencies to an incident they reported."""

    agencies: list[str] = Field(min_length=1, description="agency_type values to add.")


class AreaAgenciesResponse(BaseModel):
    """The merged agencies now requested on the citizen's report(s) for an area."""

    area_id: UUID
    agencies: list[str]
    message: str