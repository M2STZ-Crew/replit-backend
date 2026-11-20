"""Map-layer read endpoints (Phase 12, Section 7 #22-#26).

Read-only views of the GIS layers (hydrants, evacuation sites, risk zones, bodies
of water, underground cisterns), available to any authenticated user. Polygon
geometries are returned as GeoJSON. Writes + the hydrant ground-truth override are
added in later parts.

Hydrants, evacuation sites, cisterns and (v1.12.43) bodies of water can be
switched off without deleting them. Every map reads the active ones;
``include_inactive`` is for the Admin who edits the map, who would otherwise lose
sight of a row the moment they switched it off.
"""

from __future__ import annotations

import gzip
import json
import time
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, DatabaseDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import (
    BodyOfWaterResponse,
    CisternResponse,
    EvacuationSiteResponse,
    HydrantResponse,
    RiskZoneResponse,
)
from app.services.access import MANAGE_MAP, admin_access

log = get_logger(__name__)

router = APIRouter(prefix="/map", tags=["map-layers"])

_HYDRANT_COLS = (
    "id, code, latitude, longitude, address, bfp_status::text as bfp_status, "
    "bfp_synced_at, ground_truth_status::text as ground_truth_status, "
    "ground_truth_by, ground_truth_at, ground_truth_notes, "
    "effective_status::text as effective_status, source, is_active, "
    "created_at, updated_at, "
    # Who last checked it on site, and for which organisation (v1.12.43).
    "(select u.full_name from public.users u "
    " where u.id = hydrants.ground_truth_by) as checked_by_name, "
    "(select o.name from public.users u "
    " join public.organizations o on o.id = u.primary_org_id "
    " where u.id = hydrants.ground_truth_by) as checked_by_org"
)


def _for_resident(user: AuthenticatedUser, row: dict[str, object]) -> dict[str, object]:
    """Residents see where water is, never whether it works (v1.12.43): that is
    for responders, who act on it."""
    if user.role != "general_user":
        return row
    hidden: dict[str, object] = {
        "bfp_status": "unknown",
        "effective_status": "unknown",
        "ground_truth_status": None,
        "ground_truth_by": None,
        "ground_truth_at": None,
        "ground_truth_notes": None,
        "checked_by_name": None,
        "checked_by_org": None,
    }
    if "status" in row:
        hidden = {"status": "unknown"}
    return {**row, **hidden}
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
    "extensions.ST_AsGeoJSON(area_geom) as area_geojson, created_at, updated_at, "
    "is_active"
)
# Before migration 20261120090000 (v1.12.43) bodies_of_water has no is_active:
# every source is on, as before, rather than no water on any map.
_WATER_COLS_BEFORE_1_12_43 = _WATER_COLS.removesuffix(", is_active")
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
    return [HydrantResponse.model_validate(_for_resident(user, dict(r))) for r in rows]


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
    return HydrantResponse.model_validate(_for_resident(user, dict(row)))


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
    user: CurrentUser, db: DatabaseDep, include_inactive: bool = False
) -> list[BodyOfWaterResponse]:
    """List bodies of water usable as firefighting water sources. One switched
    off (v1.12.43) leaves every map but the editor's, like a hydrant."""
    try:
        rows = await db.fetch(
            f"select {_WATER_COLS} from public.bodies_of_water "
            f"{_active_only(user, include_inactive)} order by name"
        )
    except asyncpg.exceptions.UndefinedColumnError:
        log.warning("water_switch_off_waits_for_migration")
        rows = await db.fetch(
            f"select {_WATER_COLS_BEFORE_1_12_43} from public.bodies_of_water order by name"
        )
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
    try:
        row = await db.fetchrow(
            f"select {_WATER_COLS} from public.bodies_of_water where id = $1", layer_id
        )
    except asyncpg.exceptions.UndefinedColumnError:
        log.warning("water_switch_off_waits_for_migration")
        row = await db.fetchrow(
            f"select {_WATER_COLS_BEFORE_1_12_43} from public.bodies_of_water where id = $1",
            layer_id,
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
    return [CisternResponse.model_validate(_for_resident(user, dict(r))) for r in rows]


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
    return CisternResponse.model_validate(_for_resident(user, dict(row)))


# --------------------------------------------------------------------------- #
# Barangays (v1.12.45)
# --------------------------------------------------------------------------- #
# What the map calls a High zone: research-based, never a BFP designation
# (the user's risk file, 19 Nov 2026).
RISK_LABEL = "High fire-risk zone (research-based)"

# The outlines at 5 decimals (about 1 m), each drawn simplified to 2 m but for
# the High fire-risk barangays, kept as drawn.
_BARANGAY_LAYER_SQL = """
select b.pcode, b.name, b.kind, b.number, b.zone, b.district, b.city,
       extensions.ST_AsGeoJSON(
           case when r.pcode is null then b.geom_map
                else extensions.ST_Transform(b.geom, 4326) end, 5) as area_geojson,
       r.zone_id as risk_zone, r.risk_level, r.risk_source,
       r.assessment_start, r.assessment_end
  from public.barangays b
  left join public.fire_risk_barangays r on r.pcode = b.pcode
 order by b.pcode
"""

# The layer changes only when scripts/load_barangays.py runs: built once,
# kept for an hour, then built again.
_LAYER_TTL_S = 3600.0
_layer: dict[str, Any] = {"at": 0.0, "body": b"[]", "packed": gzip.compress(b"[]")}


def _barangay_row(r: Any) -> dict[str, Any]:
    risk = None
    if r["risk_level"] is not None:
        risk = {
            "zone_id": r["risk_zone"],
            "level": r["risk_level"],
            "label": RISK_LABEL,
            "source": r["risk_source"],
            "assessment_start": r["assessment_start"].isoformat(),
            "assessment_end": r["assessment_end"].isoformat(),
            "official_bfp_designation": False,
        }
    return {
        "pcode": r["pcode"],
        "name": r["name"],
        "kind": r["kind"],
        "number": r["number"],
        "zone": r["zone"],
        "district": r["district"],
        "city": r["city"],
        "area_geojson": r["area_geojson"],
        "risk": risk,
    }


async def barangay_layer(db: Database) -> tuple[bytes, bytes]:
    """The layer's JSON, plain and gzipped. Empty, and built again on the next
    call, before migration 20261120150000 or before the barangays are loaded."""
    if _layer["at"] and time.monotonic() - _layer["at"] < _LAYER_TTL_S:
        return _layer["body"], _layer["packed"]
    try:
        rows = await db.fetch(_BARANGAY_LAYER_SQL)
    except (asyncpg.exceptions.UndefinedTableError, asyncpg.exceptions.UndefinedColumnError):
        log.info("barangay_layer_waits_for_migration")
        return b"[]", gzip.compress(b"[]")
    body = json.dumps([_barangay_row(r) for r in rows], separators=(",", ":")).encode()
    packed = gzip.compress(body, compresslevel=6)
    if rows:
        _layer.update(at=time.monotonic(), body=body, packed=packed)
    log.info("barangay_layer_built", barangays=len(rows), bytes=len(body), gzipped=len(packed))
    return body, packed


@router.get(
    "/barangays",
    summary="Metro Manila's barangay outlines, with Pasay's High fire-risk zones",
    responses={
        200: {"description": "A JSON list of barangays.", "content": {"application/json": {}}}
    },
)
async def list_barangays(request: Request, user: CurrentUser, db: DatabaseDep) -> Response:
    """The barangay layer every map can switch on (v1.12.45; 19 Nov 2026: "the
    exact geographic boundary lines (polygons) of each barangay, displayed as a
    clean layer so you can color-code and highlight fire risk zones").

    Each row: PSGC code, name ("Barangay 76", "Bel-Air"), kind, number, zone,
    Manila district, city, outline (GeoJSON MultiPolygon, ``area_geojson``),
    and ``risk`` for the 86 barangays of Pasay's High fire-risk zones ("High
    fire-risk zone (research-based)", never a BFP designation), else null.
    About 1.3 MB, sent gzipped to any client that accepts it.
    """
    body, packed = await barangay_layer(db)
    headers = {"Vary": "Accept-Encoding", "Cache-Control": "private, max-age=3600"}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(
            packed,
            media_type="application/json",
            headers={**headers, "Content-Encoding": "gzip"},
        )
    return Response(body, media_type="application/json", headers=headers)
