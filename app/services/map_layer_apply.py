"""Apply an approved map_layer_update_request to its target layer (Phase 12, Section 6).

The proposed_data is validated against the layer's own create/update schema, then a
generic INSERT/UPDATE is built (handling enum casts and GeoJSON geometry). DELETE
removes the target row. Raises BadRequestError on invalid proposals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.session import Database
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate
from app.schemas.map_layer import (
    BodyOfWaterCreate,
    BodyOfWaterUpdate,
    CisternCreate,
    CisternUpdate,
    EvacuationSiteCreate,
    EvacuationSiteUpdate,
    HydrantCreate,
    HydrantUpdate,
    RiskZoneCreate,
    RiskZoneUpdate,
)


@dataclass(frozen=True)
class LayerSpec:
    """Per-layer mapping: target table, validation models, enum-cast columns."""

    table: str
    create_model: type[BaseModel]
    update_model: type[BaseModel]
    enum_casts: dict[str, str]


LAYER_SPECS: dict[str, LayerSpec] = {
    "hydrant": LayerSpec(
        "hydrants", HydrantCreate, HydrantUpdate, {"bfp_status": "public.hydrant_status"}
    ),
    "evacuation_site": LayerSpec(
        "evacuation_sites", EvacuationSiteCreate, EvacuationSiteUpdate, {}
    ),
    "risk_zone": LayerSpec(
        "risk_zones", RiskZoneCreate, RiskZoneUpdate, {"risk_level": "public.risk_level"}
    ),
    "bodies_of_water": LayerSpec(
        "bodies_of_water", BodyOfWaterCreate, BodyOfWaterUpdate, {}
    ),
    "underground_cistern": LayerSpec(
        "underground_cisterns", CisternCreate, CisternUpdate, {"status": "public.hydrant_status"}
    ),
    "equipment": LayerSpec(
        "equipment", EquipmentCreate, EquipmentUpdate, {"status": "public.equipment_status"}
    ),
}


def _column_sql(
    key: str, params: list[Any], value: Any, enum_casts: dict[str, str]
) -> tuple[str, str]:
    """Return (column, placeholder) for one field, appending its value to params."""
    if key == "area_geojson":
        params.append(value)
        return "area_geom", f"extensions.ST_GeomFromGeoJSON(${len(params)})::geography"
    params.append(value)
    if key in enum_casts:
        return key, f"${len(params)}::{enum_casts[key]}"
    return key, f"${len(params)}"


async def _do_create(db: Database, spec: LayerSpec, data: dict[str, Any]) -> UUID:
    """Insert a new layer row from validated data; return its id."""
    cols: list[str] = []
    placeholders: list[str] = []
    params: list[Any] = []
    for key, value in data.items():
        col, ph = _column_sql(key, params, value, spec.enum_casts)
        cols.append(col)
        placeholders.append(ph)
    new_id = await db.fetchval(
        f"insert into public.{spec.table} ({', '.join(cols)}) "
        f"values ({', '.join(placeholders)}) returning id",
        *params,
    )
    return UUID(str(new_id))


async def _do_update(
    db: Database, spec: LayerSpec, target_id: UUID, data: dict[str, Any]
) -> UUID:
    """Update an existing layer row from validated (partial) data; return its id."""
    if not data:
        raise BadRequestError("Update request has no fields to apply.")
    set_parts: list[str] = []
    params: list[Any] = [target_id]
    for key, value in data.items():
        if key == "area_geojson" and value is None:
            set_parts.append("area_geom = null")
            continue
        col, ph = _column_sql(key, params, value, spec.enum_casts)
        set_parts.append(f"{col} = {ph}")
    result = await db.execute(
        f"update public.{spec.table} set {', '.join(set_parts)} where id = $1",
        *params,
    )
    if result.endswith(" 0"):
        raise NotFoundError("Target record not found.")
    return target_id


async def apply_map_layer_request(
    db: Database,
    layer_type: str,
    operation: str,
    target_id: UUID | None,
    proposed_data: dict[str, Any],
) -> UUID:
    """Apply an approved request to its target layer; return the affected row id."""
    spec = LAYER_SPECS.get(layer_type)
    if spec is None:
        raise BadRequestError(f"Unsupported layer type: {layer_type}.")

    if operation == "delete":
        if target_id is None:
            raise BadRequestError("A delete request requires target_id.")
        result = await db.execute(
            f"delete from public.{spec.table} where id = $1", target_id
        )
        if result.endswith(" 0"):
            raise NotFoundError("Target record not found.")
        return target_id

    if operation == "create":
        try:
            model = spec.create_model.model_validate(proposed_data)
        except ValidationError as exc:
            raise BadRequestError(f"Invalid proposed_data for create: {exc}") from exc
        return await _do_create(db, spec, model.model_dump())

    if operation == "update":
        if target_id is None:
            raise BadRequestError("An update request requires target_id.")
        try:
            model = spec.update_model.model_validate(proposed_data)
        except ValidationError as exc:
            raise BadRequestError(f"Invalid proposed_data for update: {exc}") from exc
        return await _do_update(db, spec, target_id, model.model_dump(exclude_unset=True))

    raise BadRequestError(f"Unsupported operation: {operation}.")