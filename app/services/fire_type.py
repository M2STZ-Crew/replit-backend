"""What is burning: the fire types and their subtypes (PRD v14 §4.5.3).

The first unit on scene picks one (Figma C18 / R08b, "What's burning?"); it
unlocks the on-scene requests and goes into the reports. The values are the
database's checks (supabase/migrations/20261112090000_fire_type_on_arrival.sql)
and the app's FireType (lib/models/field_ops.dart). PRD v14 took Agricultural
out of Structural: Pasay has no agricultural land.
"""

from __future__ import annotations

from typing import Literal

from app.core.exceptions import BadRequestError

FireTypeValue = Literal["structural", "electrical", "vehicular", "rubbish", "grass", "chemical"]

FIRE_SUBTYPES: dict[str, tuple[str, ...]] = {
    "structural": ("residential", "commercial", "industrial"),
    "electrical": ("high_tension_wire", "transformer", "entrance_wire", "meter"),
    "vehicular": ("motorcycle", "tricycle", "sedan", "suv", "truck", "e_bike", "e_car"),
    "rubbish": (),
    "grass": (),
    "chemical": (),
}

# Where a fire type can be set: on scene, and afterwards to correct it before
# the Area closes.
ON_SCENE_STATUSES = frozenset({"arrived", "fire_out", "post_incident_report"})


def validate_fire_type(fire_type: str, subtype: str | None) -> str | None:
    """The subtype to store for ``fire_type``: one of its own when it has them,
    else None. Raises a 400 ``invalid_fire_subtype`` otherwise."""
    allowed = FIRE_SUBTYPES.get(fire_type)
    if allowed is None:
        raise BadRequestError(
            "Pick what is burning from the list.",
            error_code="invalid_fire_type",
            details={"field": "fire_type"},
        )
    subtype = (subtype or "").strip().lower() or None
    if not allowed:
        if subtype is not None:
            raise BadRequestError(
                "This fire type has no subtype.",
                error_code="invalid_fire_subtype",
                details={"field": "fire_subtype", "fire_type": fire_type},
            )
        return None
    if subtype not in allowed:
        raise BadRequestError(
            "Pick the kind of fire from the list.",
            error_code="invalid_fire_subtype",
            details={"field": "fire_subtype", "fire_type": fire_type, "allowed": list(allowed)},
        )
    return subtype
