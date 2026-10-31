"""Map-layer read endpoints (Phase 12, Section 7 #22-#26).

Read-only views of the GIS layers (hydrants, evacuation sites, risk zones, bodies
of water, underground cisterns), available to any authenticated user. Polygon
geometries are returned as GeoJSON. Writes + the hydrant ground-truth override are
added in later parts.

Hydrants, evacuation sites and cisterns can be switched off without deleting them.
Every map reads the active ones; ``include_inactive`` is for the Admin who edits
the map, who would otherwise lose sight of a row the moment they switched it off.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep
from app.core.exceptions import NotFoundError
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import (
    BodyOfWaterResponse,
    CisternResponse,
    EvacuationSiteResponse,
    HydrantResponse,
    RiskZoneResponse,
)
from app.services.access import MANAGE_MAP, admin_access

router = APIRouter(prefix="/map", tags=["map-layers"])

_HYDRANT_COLS = (
    "id, code, latitude, longitude, address, bfp_status::text as bfp_status, "
    "bfp_synced_at, ground_truth_status::text as ground_truth_status, "
    "ground_truth_by, ground_truth_at, ground_truth_notes, "
    "effective_status::text as effective_status, source, is_active, "
    "created_at, updated_at"
)
_EVAC_COLS = (
    "id, name, latitude, longitude, capacity, address, contact_info, "
    "city, outside_pasay, is_active, created_at, updated_at"
)
_RISK_COLS = (
    "id, barangay, name, risk_level::text as risk_level, description, "
    "centroid_lat, centroid_lng, radius_m, "
    "extensions.ST_AsGeoJSON(area_geom) as area_geojson, created_at, updated_at"
)
_WATER_COLS = (
    "id, name, water_type, latitude, longitude, is_accessible, description, "
    "extensions.ST_AsGeoJSON(area_geom) as area_geojson, created_at, updated_at"
)
_CISTERN_COLS = (
    "id, name, code, latitude, longitude, capacity_liters, status::text as status, "
    "address, description, is_active, created_at, updated_at"
)


def _active_only(user: AuthenticatedUser, include_inactive: bool) -> str:
    """The ``where`` for a list: active rows, unless the map's editor asks for all."""
    access = admin_access(user)
    if include_inactive and access is not None and access.can(MANAGE_MAP):
        return ""
    return "where is_active"


# --------------------------------------------------------------------------- #
# Hydrants
# --------------------------------------------------------------------------- #
@router.get("/hydrants", response_model=list[HydrantResponse], summary="List hydrants")
async def list_hydrants(
    user: CurrentUser, db: DatabaseDep, include_inactive: bool = False
) -> list[HydrantResponse]:
    """List active hydrants with their effective status."""
    rows = await db.fetch(
        f"select {_HYDRANT_COLS} from public.hydrants "
        f"{_active_only(user, include_inactive)} order by code nulls last"
    )
    return [HydrantResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/hydrants/{layer_id}", response_model=HydrantResponse, summary="Get a hydrant"
)
async def get_hydrant(
    layer_id: UUID, user: CurrentUser, db: DatabaseDep
) -> HydrantResponse:
    """Get one hydrant by id."""
    row = await db.fetchrow(
        f"select {_HYDRANT_COLS} from public.hydrants where id = $1", layer_id
    )
    if row is None:
        raise NotFoundError("Hydrant not found.")
    return HydrantResponse.model_validate(dict(row))


# --------------------------------------------------------------------------- #
# Evacuation sites
# --------------------------------------------------------------------------- #
@router.get(
    "/evacuation-sites",
    response_model=list[EvacuationSiteResponse],
    summary="List evacuation sites",
)
async def list_evacuation_sites(
    user: CurrentUser, db: DatabaseDep, include_inactive: bool = False
) -> list[EvacuationSiteResponse]:
    """List active evacuation sites."""
    rows = await db.fetch(
        f"select {_EVAC_COLS} from public.evacuation_sites "
        f"{_active_only(user, include_inactive)} order by name"
    )
    return [EvacuationSiteResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/evacuation-sites/{layer_id}",
    response_model=EvacuationSiteResponse,
    summary="Get an evacuation site",
)
async def get_evacuation_site(
    layer_id: UUID, user: CurrentUser, db: DatabaseDep
) -> EvacuationSiteResponse:
    """Get one evacuation site by id."""
    row = await db.fetchrow(
        f"select {_EVAC_COLS} from public.evacuation_sites where id = $1", layer_id
    )
    if row is None:
        raise NotFoundError("Evacuation site not found.")
    return EvacuationSiteResponse.model_validate(dict(row))


# --------------------------------------------------------------------------- #
# Risk zones
# --------------------------------------------------------------------------- #
@router.get("/risk-zones", response_model=list[RiskZoneResponse], summary="List risk zones")
async def list_risk_zones(user: CurrentUser, db: DatabaseDep) -> list[RiskZoneResponse]:
    """List BFP per-barangay risk zones."""
    rows = await db.fetch(f"select {_RISK_COLS} from public.risk_zones order by barangay")
    return [RiskZoneResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/risk-zones/{layer_id}", response_model=RiskZoneResponse, summary="Get a risk zone"
)
async def get_risk_zone(
    layer_id: UUID, user: CurrentUser, db: DatabaseDep
) -> RiskZoneResponse:
    """Get one risk zone by id."""
    row = await db.fetchrow(
        f"select {_RISK_COLS} from public.risk_zones where id = $1", layer_id
    )
    if row is None:
        raise NotFoundError("Risk zone not found.")
    return RiskZoneResponse.model_validate(dict(row))


# --------------------------------------------------------------------------- #
# Bodies of water
# --------------------------------------------------------------------------- #
@router.get(
    "/bodies-of-water",
    response_model=list[BodyOfWaterResponse],
    summary="List bodies of water",
)
async def list_bodies_of_water(
    user: CurrentUser, db: DatabaseDep
) -> list[BodyOfWaterResponse]:
    """List bodies of water usable as firefighting water sources."""
    rows = await db.fetch(f"select {_WATER_COLS} from public.bodies_of_water order by name")
    return [BodyOfWaterResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/bodies-of-water/{layer_id}",
    response_model=BodyOfWaterResponse,
    summary="Get a body of water",
)
async def get_body_of_water(
    layer_id: UUID, user: CurrentUser, db: DatabaseDep
) -> BodyOfWaterResponse:
    """Get one body of water by id."""
    row = await db.fetchrow(
        f"select {_WATER_COLS} from public.bodies_of_water where id = $1", layer_id
    )
    if row is None:
        raise NotFoundError("Body of water not found.")
    return BodyOfWaterResponse.model_validate(dict(row))


# --------------------------------------------------------------------------- #
# Underground cisterns
# --------------------------------------------------------------------------- #
@router.get(
    "/underground-cisterns",
    response_model=list[CisternResponse],
    summary="List underground cisterns",
)
async def list_cisterns(
    user: CurrentUser, db: DatabaseDep, include_inactive: bool = False
) -> list[CisternResponse]:
    """List active underground cisterns."""
    rows = await db.fetch(
        f"select {_CISTERN_COLS} from public.underground_cisterns "
        f"{_active_only(user, include_inactive)} order by code nulls last"
    )
    return [CisternResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/underground-cisterns/{layer_id}",
    response_model=CisternResponse,
    summary="Get an underground cistern",
)
async def get_cistern(
    layer_id: UUID, user: CurrentUser, db: DatabaseDep
) -> CisternResponse:
    """Get one underground cistern by id."""
    row = await db.fetchrow(
        f"select {_CISTERN_COLS} from public.underground_cisterns where id = $1", layer_id
    )
    if row is None:
        raise NotFoundError("Underground cistern not found.")
    return CisternResponse.model_validate(dict(row))