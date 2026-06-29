"""Incident lifecycle schemas (Phase 9, Section 9).

An "incident" is a public.areas row plus its dispatch + responder context. Reads
expose the 7 lifecycle timestamps and the current alarm level; the request bodies
drive status transitions and the dispatch / responder-GPS writes (Parts 2-4).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Read models
# --------------------------------------------------------------------------- #
class IncidentReportItem(BaseModel):
    """A member report contributing to an incident area."""

    id: UUID
    device_lat: float
    device_lng: float
    has_exif: bool
    gps_discrepancy_flag: bool
    user_verified_percent: int
    selected_agencies: list[str] = Field(default_factory=list)
    created_at: datetime


class IncidentReportDetail(BaseModel):
    """A member report with reviewer context: reporter name + signed photo URL."""

    id: UUID
    reporter_id: UUID | None = None
    reporter_name: str | None = None
    photo_url: str | None = None
    device_lat: float
    device_lng: float
    has_exif: bool
    gps_discrepancy_flag: bool
    user_verified_percent: int
    selected_agencies: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime


class AvailableResponder(BaseModel):
    """A response_team user a sub-admin can dispatch (for the dispatch crew picker)."""

    id: UUID
    full_name: str | None = None
    agency_type: str | None = None
    organization_id: UUID | None = None
    is_busy: bool = False  # has an active dispatch to any incident
    on_this_incident: bool = False  # already actively dispatched to this incident


class IncidentStats(BaseModel):
    """Counters for the responder dashboard (visibility / agency scoped)."""

    active_incidents: int = 0
    pending_verify: int = 0
    units_deployed: int = 0
    units_standby: int = 0


class IncidentSummary(BaseModel):
    """Compact incident for the operational feed (visibility-filtered)."""

    id: UUID
    designation: str
    status: str
    centroid_lat: float
    centroid_lng: float
    report_count: int
    confidence_score: float
    confidence_band: str
    alarm_level: str | None = None
    active_dispatch_count: int = 0
    reported_at: datetime
    verified_at: datetime | None = None
    dispatched_at: datetime | None = None
    en_route_at: datetime | None = None
    arrived_at: datetime | None = None
    resolved_at: datetime | None = None
    rejected_at: datetime | None = None
    updated_at: datetime


class IncidentDetail(IncidentSummary):
    """Full incident with confidence components, accountability, and member reports."""

    n_score: float
    s_score: float
    v_score: float
    version: int
    parent_area_id: UUID | None = None
    verified_by: UUID | None = None
    verified_by_name: str | None = None
    resolved_by: UUID | None = None
    resolved_by_name: str | None = None
    rejected_by: UUID | None = None
    rejected_by_name: str | None = None
    rejection_reason: str | None = None
    alarm_level_set_by: UUID | None = None
    alarm_level_set_at: datetime | None = None
    reports: list[IncidentReportItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Request models (Parts 2-4)
# --------------------------------------------------------------------------- #
class IncidentRejectRequest(BaseModel):
    """Reject an incident as invalid / a false report."""

    reason: str = Field(
        min_length=1, max_length=1000, description="Why the incident is being rejected."
    )


class ManualDispatchRequest(BaseModel):
    """A sub-admin assigns a response_team member to an incident (manual dispatch)."""

    responder_id: UUID = Field(description="The response_team user being dispatched.")
    organization_id: UUID | None = Field(
        default=None, description="Responder's organization, if applicable."
    )
    vehicle_name: str | None = Field(
        default=None, max_length=200, description="The unit/truck this responder crews."
    )
    crew_role: str | None = Field(
        default=None, max_length=100, description="Fireground role (e.g. Driver / Pump Op)."
    )
    notes: str | None = Field(default=None, max_length=1000)


class SelfDispatchRequest(BaseModel):
    """A response_team member self-selects onto an incident (self-select dispatch)."""

    organization_id: UUID | None = Field(
        default=None, description="Responder's organization, if applicable."
    )
    notes: str | None = Field(default=None, max_length=1000)


class ResponderLocationCreate(BaseModel):
    """A single GPS fix posted by a responder during active response (5 s cadence)."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    captured_at: datetime = Field(description="Device-side timestamp of the fix.")
    accuracy_m: float | None = Field(default=None, ge=0)
    speed_mps: float | None = Field(default=None, ge=0)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    dispatch_id: UUID | None = Field(
        default=None, description="The dispatch this fix belongs to, if known."
    )


# --------------------------------------------------------------------------- #
# Dispatch / responder response models (Parts 3-4)
# --------------------------------------------------------------------------- #
class DispatchItem(BaseModel):
    """A dispatch assignment row."""

    id: UUID
    area_id: UUID
    responder_id: UUID
    responder_name: str | None = None
    organization_id: UUID | None = None
    dispatch_type: str
    dispatched_by: UUID | None = None
    status: str
    dispatched_at: datetime
    withdrawn_at: datetime | None = None
    completed_at: datetime | None = None
    vehicle_name: str | None = None
    crew_role: str | None = None
    notes: str | None = None


class ResponderLocationItem(BaseModel):
    """The latest known location of a responder on an incident."""

    responder_id: UUID
    lat: float
    lng: float
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    captured_at: datetime
    created_at: datetime
    dispatch_id: UUID | None = None