"""Map-layer write endpoints (Phase 12, Section 7 #22-#26) — admin create/update/delete.

Direct edits to the GIS layers are admin-only; non-admin sub-admins use the
map_layer_update_requests workflow (Part 6). The hydrant ground-truth override and
BFP CSV import live in their own module (Part 5). Polygon geometry is accepted as a
GeoJSON geometry and stored as geography.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import AdminUser, DatabaseDep
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.map_layer import (
    BodyOfWaterCreate,
    BodyOfWaterResponse,
    BodyOfWaterUpdate,
    CisternCreate,
    CisternResponse,
    CisternUpdate,
    EvacuationSiteCreate,
    EvacuationSiteResponse,
    EvacuationSiteUpdate,
    HydrantCreate,
    HydrantResponse,
    HydrantUpdate,
    RiskZoneCreate,
    RiskZoneResponse,
    RiskZoneUpdate,
)

log = get_logger(__name__)

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
    "is_active, created_at, updated_at"
)
_RISK_COLS = (
    "id, barangay, name, risk_level::text as risk_level, description, "
    "centroid_lat, centroid_lng, "
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


async def _apply_update(
    db: Database,
    table: str,
    layer_id: UUID,
    returning_cols: str,
    fields: dict[str, Any],
    not_found_msg: str,
    *,
    enum_casts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Patch one row from a fields dict, handling enum casts and GeoJSON geometry."""
    enum_casts = enum_casts or {}
    if not fields:
        raise BadRequestError("No fields provided to update.")
    set_parts: list[str] = []
    params: list[Any] = [layer_id]
    for key, value in fields.items():
        if key == "area_geojson":
            if value is None:
                set_parts.append("area_geom = null")
            else:
                params.append(value)
                set_parts.append(
                    f"area_geom = extensions.ST_GeomFromGeoJSON(${len(params)})::geography"
                )
            continue
        params.append(value)
        if key in enum_casts:
            set_parts.append(f"{key} = ${len(params)}::{enum_casts[key]}")
        else:
            set_parts.append(f"{key} = ${len(params)}")
    row = await db.fetchrow(
        f"update public.{table} set {', '.join(set_parts)} "
        f"where id = $1 returning {returning_cols}",
        *params,
    )
    if row is None:
        raise NotFoundError(not_found_msg)
    return dict(row)


async def _delete_layer(db: Database, table: str, layer_id: UUID, not_found_msg: str) -> None:
    """Delete one row by id; raise 404 if nothing was deleted."""
    result = await db.execute(f"delete from public.{table} where id = $1", layer_id)
    if result.endswith(" 0"):
        raise NotFoundError(not_found_msg)


# --------------------------------------------------------------------------- #
# Hydrants
# --------------------------------------------------------------------------- #
@router.post(
    "/hydrants",
    response_model=HydrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a hydrant (admin)",
)
async def create_hydrant(
    payload: HydrantCreate, admin: AdminUser, db: DatabaseDep
) -> HydrantResponse:
    """Create a hydrant record (admin)."""
    row = await db.fetchrow(
        f"""
        insert into public.hydrants
            (code, latitude, longitude, address, bfp_status, source, is_active)
        values ($1, $2, $3, $4, $5::public.hydrant_status, $6, $7)
        returning {_HYDRANT_COLS}
        """,
        payload.code,
        payload.latitude,
        payload.longitude,
        payload.address,
        payload.bfp_status,
        payload.source,
        payload.is_active,
    )
    assert row is not None
    log.info("hydrant_created", layer_id=str(row["id"]), by=str(admin.id))
    return HydrantResponse.model_validate(dict(row))


@router.patch(
    "/hydrants/{layer_id}", response_model=HydrantResponse, summary="Update a hydrant (admin)"
)
async def update_hydrant(
    layer_id: UUID, payload: HydrantUpdate, admin: AdminUser, db: DatabaseDep
) -> HydrantResponse:
    """Patch a hydrant's base fields (admin)."""
    updated = await _apply_update(
        db,
        "hydrants",
        layer_id,
        _HYDRANT_COLS,
        payload.model_dump(exclude_unset=True),
        "Hydrant not found.",
        enum_casts={"bfp_status": "public.hydrant_status"},
    )
    log.info("hydrant_updated", layer_id=str(layer_id), by=str(admin.id))
    return HydrantResponse.model_validate(updated)


@router.delete(
    "/hydrants/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a hydrant (admin)",
)
async def delete_hydrant(layer_id: UUID, admin: AdminUser, db: DatabaseDep) -> Response:
    """Delete a hydrant (admin)."""
    await _delete_layer(db, "hydrants", layer_id, "Hydrant not found.")
    log.info("hydrant_deleted", layer_id=str(layer_id), by=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Evacuation sites
# --------------------------------------------------------------------------- #
@router.post(
    "/evacuation-sites",
    response_model=EvacuationSiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an evacuation site (admin)",
)
async def create_evacuation_site(
    payload: EvacuationSiteCreate, admin: AdminUser, db: DatabaseDep
) -> EvacuationSiteResponse:
    """Create an evacuation site (admin)."""
    row = await db.fetchrow(
        f"""
        insert into public.evacuation_sites
            (name, latitude, longitude, capacity, address, contact_info, is_active)
        values ($1, $2, $3, $4, $5, $6, $7)
        returning {_EVAC_COLS}
        """,
        payload.name,
        payload.latitude,
        payload.longitude,
        payload.capacity,
        payload.address,
        payload.contact_info,
        payload.is_active,
    )
    assert row is not None
    log.info("evacuation_site_created", layer_id=str(row["id"]), by=str(admin.id))
    return EvacuationSiteResponse.model_validate(dict(row))


@router.patch(
    "/evacuation-sites/{layer_id}",
    response_model=EvacuationSiteResponse,
    summary="Update an evacuation site (admin)",
)
async def update_evacuation_site(
    layer_id: UUID, payload: EvacuationSiteUpdate, admin: AdminUser, db: DatabaseDep
) -> EvacuationSiteResponse:
    """Patch an evacuation site (admin)."""
    updated = await _apply_update(
        db,
        "evacuation_sites",
        layer_id,
        _EVAC_COLS,
        payload.model_dump(exclude_unset=True),
        "Evacuation site not found.",
    )
    log.info("evacuation_site_updated", layer_id=str(layer_id), by=str(admin.id))
    return EvacuationSiteResponse.model_validate(updated)


@router.delete(
    "/evacuation-sites/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an evacuation site (admin)",
)
async def delete_evacuation_site(
    layer_id: UUID, admin: AdminUser, db: DatabaseDep
) -> Response:
    """Delete an evacuation site (admin)."""
    await _delete_layer(db, "evacuation_sites", layer_id, "Evacuation site not found.")
    log.info("evacuation_site_deleted", layer_id=str(layer_id), by=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Risk zones
# --------------------------------------------------------------------------- #
@router.post(
    "/risk-zones",
    response_model=RiskZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a risk zone (admin)",
)
async def create_risk_zone(
    payload: RiskZoneCreate, admin: AdminUser, db: DatabaseDep
) -> RiskZoneResponse:
    """Create a risk zone; optional GeoJSON polygon boundary (admin)."""
    row = await db.fetchrow(
        f"""
        insert into public.risk_zones
            (barangay, name, risk_level, description, centroid_lat, centroid_lng, area_geom)
        values ($1, $2, $3::public.risk_level, $4, $5, $6,
                extensions.ST_GeomFromGeoJSON($7)::geography)
        returning {_RISK_COLS}
        """,
        payload.barangay,
        payload.name,
        payload.risk_level,
        payload.description,
        payload.centroid_lat,
        payload.centroid_lng,
        payload.area_geojson,
    )
    assert row is not None
    log.info("risk_zone_created", layer_id=str(row["id"]), by=str(admin.id))
    return RiskZoneResponse.model_validate(dict(row))


@router.patch(
    "/risk-zones/{layer_id}",
    response_model=RiskZoneResponse,
    summary="Update a risk zone (admin)",
)
async def update_risk_zone(
    layer_id: UUID, payload: RiskZoneUpdate, admin: AdminUser, db: DatabaseDep
) -> RiskZoneResponse:
    """Patch a risk zone (admin)."""
    updated = await _apply_update(
        db,
        "risk_zones",
        layer_id,
        _RISK_COLS,
        payload.model_dump(exclude_unset=True),
        "Risk zone not found.",
        enum_casts={"risk_level": "public.risk_level"},
    )
    log.info("risk_zone_updated", layer_id=str(layer_id), by=str(admin.id))
    return RiskZoneResponse.model_validate(updated)


@router.delete(
    "/risk-zones/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a risk zone (admin)",
)
async def delete_risk_zone(layer_id: UUID, admin: AdminUser, db: DatabaseDep) -> Response:
    """Delete a risk zone (admin)."""
    await _delete_layer(db, "risk_zones", layer_id, "Risk zone not found.")
    log.info("risk_zone_deleted", layer_id=str(layer_id), by=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Bodies of water
# --------------------------------------------------------------------------- #
@router.post(
    "/bodies-of-water",
    response_model=BodyOfWaterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a body of water (admin)",
)
async def create_body_of_water(
    payload: BodyOfWaterCreate, admin: AdminUser, db: DatabaseDep
) -> BodyOfWaterResponse:
    """Create a body of water; optional GeoJSON polygon (admin)."""
    row = await db.fetchrow(
        f"""
        insert into public.bodies_of_water
            (name, water_type, latitude, longitude, is_accessible, description, area_geom)
        values ($1, $2, $3, $4, $5, $6, extensions.ST_GeomFromGeoJSON($7)::geography)
        returning {_WATER_COLS}
        """,
        payload.name,
        payload.water_type,
        payload.latitude,
        payload.longitude,
        payload.is_accessible,
        payload.description,
        payload.area_geojson,
    )
    assert row is not None
    log.info("body_of_water_created", layer_id=str(row["id"]), by=str(admin.id))
    return BodyOfWaterResponse.model_validate(dict(row))


@router.patch(
    "/bodies-of-water/{layer_id}",
    response_model=BodyOfWaterResponse,
    summary="Update a body of water (admin)",
)
async def update_body_of_water(
    layer_id: UUID, payload: BodyOfWaterUpdate, admin: AdminUser, db: DatabaseDep
) -> BodyOfWaterResponse:
    """Patch a body of water (admin)."""
    updated = await _apply_update(
        db,
        "bodies_of_water",
        layer_id,
        _WATER_COLS,
        payload.model_dump(exclude_unset=True),
        "Body of water not found.",
    )
    log.info("body_of_water_updated", layer_id=str(layer_id), by=str(admin.id))
    return BodyOfWaterResponse.model_validate(updated)


@router.delete(
    "/bodies-of-water/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a body of water (admin)",
)
async def delete_body_of_water(
    layer_id: UUID, admin: AdminUser, db: DatabaseDep
) -> Response:
    """Delete a body of water (admin)."""
    await _delete_layer(db, "bodies_of_water", layer_id, "Body of water not found.")
    log.info("body_of_water_deleted", layer_id=str(layer_id), by=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Underground cisterns
# --------------------------------------------------------------------------- #
@router.post(
    "/underground-cisterns",
    response_model=CisternResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an underground cistern (admin)",
)
async def create_cistern(
    payload: CisternCreate, admin: AdminUser, db: DatabaseDep
) -> CisternResponse:
    """Create an underground cistern (admin)."""
    row = await db.fetchrow(
        f"""
        insert into public.underground_cisterns
            (name, code, latitude, longitude, capacity_liters, status, address,
             description, is_active)
        values ($1, $2, $3, $4, $5, $6::public.hydrant_status, $7, $8, $9)
        returning {_CISTERN_COLS}
        """,
        payload.name,
        payload.code,
        payload.latitude,
        payload.longitude,
        payload.capacity_liters,
        payload.status,
        payload.address,
        payload.description,
        payload.is_active,
    )
    assert row is not None
    log.info("cistern_created", layer_id=str(row["id"]), by=str(admin.id))
    return CisternResponse.model_validate(dict(row))


@router.patch(
    "/underground-cisterns/{layer_id}",
    response_model=CisternResponse,
    summary="Update an underground cistern (admin)",
)
async def update_cistern(
    layer_id: UUID, payload: CisternUpdate, admin: AdminUser, db: DatabaseDep
) -> CisternResponse:
    """Patch an underground cistern (admin)."""
    updated = await _apply_update(
        db,
        "underground_cisterns",
        layer_id,
        _CISTERN_COLS,
        payload.model_dump(exclude_unset=True),
        "Underground cistern not found.",
        enum_casts={"status": "public.hydrant_status"},
    )
    log.info("cistern_updated", layer_id=str(layer_id), by=str(admin.id))
    return CisternResponse.model_validate(updated)


@router.delete(
    "/underground-cisterns/{layer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an underground cistern (admin)",
)
async def delete_cistern(layer_id: UUID, admin: AdminUser, db: DatabaseDep) -> Response:
    """Delete an underground cistern (admin)."""
    await _delete_layer(db, "underground_cisterns", layer_id, "Underground cistern not found.")
    log.info("cistern_deleted", layer_id=str(layer_id), by=str(admin.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)