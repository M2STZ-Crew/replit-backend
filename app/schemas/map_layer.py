"""Map-layer schemas (Phase 12, Section 7 #22-#26): hydrants, evacuation sites,
risk zones, bodies of water, underground cisterns."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

HydrantStatus = Literal["operational", "non_operational", "under_maintenance", "unknown"]
RiskLevel = Literal["low", "medium", "high", "critical"]


# --------------------------------------------------------------------------- #
# Hydrants
# --------------------------------------------------------------------------- #
class HydrantCreate(BaseModel):
    """Create a hydrant (ground-truth fields are set via the override endpoint)."""

    code: str | None = Field(default=None, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=500)
    bfp_status: HydrantStatus = "unknown"
    source: str = Field(default="manual", max_length=100)
    is_active: bool = True


class HydrantUpdate(BaseModel):
    """Patch a hydrant's base fields (not the ground-truth override)."""

    code: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=500)
    bfp_status: HydrantStatus | None = None
    source: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class HydrantResponse(BaseModel):
    """A hydrant row; effective_status = ground-truth override else BFP status."""

    id: UUID
    code: str | None = None
    latitude: float
    longitude: float
    address: str | None = None
    bfp_status: str
    bfp_synced_at: datetime | None = None
    ground_truth_status: str | None = None
    ground_truth_by: UUID | None = None
    ground_truth_at: datetime | None = None
    ground_truth_notes: str | None = None
    effective_status: str
    source: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Evacuation sites
# --------------------------------------------------------------------------- #
class EvacuationSiteCreate(BaseModel):
    """Create an evacuation site."""

    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    capacity: int | None = Field(default=None, ge=0)
    address: str | None = Field(default=None, max_length=500)
    contact_info: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class EvacuationSiteUpdate(BaseModel):
    """Patch an evacuation site."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    capacity: int | None = Field(default=None, ge=0)
    address: str | None = Field(default=None, max_length=500)
    contact_info: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class EvacuationSiteResponse(BaseModel):
    """An evacuation site row."""

    id: UUID
    name: str
    latitude: float
    longitude: float
    capacity: int | None = None
    address: str | None = None
    contact_info: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Risk zones
# --------------------------------------------------------------------------- #
class RiskZoneCreate(BaseModel):
    """Create a risk zone (representative centroid required; polygon optional)."""

    barangay: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    risk_level: RiskLevel = "medium"
    description: str | None = Field(default=None, max_length=2000)
    centroid_lat: float = Field(ge=-90, le=90)
    centroid_lng: float = Field(ge=-180, le=180)
    area_geojson: str | None = Field(default=None, description="GeoJSON Polygon geometry.")


class RiskZoneUpdate(BaseModel):
    """Patch a risk zone."""

    barangay: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    risk_level: RiskLevel | None = None
    description: str | None = Field(default=None, max_length=2000)
    centroid_lat: float | None = Field(default=None, ge=-90, le=90)
    centroid_lng: float | None = Field(default=None, ge=-180, le=180)
    area_geojson: str | None = None


class RiskZoneResponse(BaseModel):
    """A risk zone row; area returned as GeoJSON when present."""

    id: UUID
    barangay: str
    name: str | None = None
    risk_level: str
    description: str | None = None
    centroid_lat: float
    centroid_lng: float
    area_geojson: str | None = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Bodies of water
# --------------------------------------------------------------------------- #
class BodyOfWaterCreate(BaseModel):
    """Create a body of water (firefighting water source)."""

    name: str = Field(min_length=1, max_length=200)
    water_type: str | None = Field(default=None, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_accessible: bool = True
    description: str | None = Field(default=None, max_length=2000)
    area_geojson: str | None = Field(default=None, description="GeoJSON Polygon geometry.")


class BodyOfWaterUpdate(BaseModel):
    """Patch a body of water."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    water_type: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_accessible: bool | None = None
    description: str | None = Field(default=None, max_length=2000)
    area_geojson: str | None = None


class BodyOfWaterResponse(BaseModel):
    """A body-of-water row; area returned as GeoJSON when present."""

    id: UUID
    name: str
    water_type: str | None = None
    latitude: float
    longitude: float
    is_accessible: bool
    description: str | None = None
    area_geojson: str | None = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Underground cisterns
# --------------------------------------------------------------------------- #
class CisternCreate(BaseModel):
    """Create an underground cistern."""

    name: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    capacity_liters: int | None = Field(default=None, ge=0)
    status: HydrantStatus = "unknown"
    address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class CisternUpdate(BaseModel):
    """Patch an underground cistern."""

    name: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    capacity_liters: int | None = Field(default=None, ge=0)
    status: HydrantStatus | None = None
    address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class CisternResponse(BaseModel):
    """An underground cistern row."""

    id: UUID
    name: str | None = None
    code: str | None = None
    latitude: float
    longitude: float
    capacity_liters: int | None = None
    status: str
    address: str | None = None
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

class HydrantGroundTruthRequest(BaseModel):
    """Fire-Volunteer ground-truth override for a hydrant."""

    status: HydrantStatus
    notes: str | None = Field(default=None, max_length=1000)


class HydrantImportResult(BaseModel):
    """Summary of a BFP hydrant CSV import."""

    created: int
    updated: int
    errors: list[str] = Field(default_factory=list)