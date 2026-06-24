"""Phase 12 (equipment, affiliates, map layers) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.equipment import _can_manage_org, _can_view_org
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer_request import MapLayerRequestCreate
from app.services.map_layer_apply import LAYER_SPECS, _column_sql


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _user(role: str, agency: str | None = None, org: object = None) -> AuthenticatedUser:
    """Build a minimal AuthenticatedUser."""
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency, primary_org_id=org)


# --------------------------------------------------------------------------- #
# Equipment RBAC helpers
# --------------------------------------------------------------------------- #
def test_equipment_rbac_helpers() -> None:
    """Admin manages/views any org; sub-admin only their own; response_team view-only."""
    org = uuid4()
    other = uuid4()
    assert _can_manage_org(_user("admin"), org) is True
    assert _can_view_org(_user("admin"), org) is True
    assert _can_manage_org(_user("sub_admin", "bfp", org), org) is True
    assert _can_manage_org(_user("sub_admin", "bfp", other), org) is False
    assert _can_view_org(_user("response_team", "bfp", org), org) is True
    assert _can_manage_org(_user("response_team", "bfp", org), org) is False


# --------------------------------------------------------------------------- #
# Map-layer apply: column builder + spec coverage
# --------------------------------------------------------------------------- #
def test_column_sql_plain_enum_and_geojson() -> None:
    """_column_sql handles plain, enum-cast, and GeoJSON-geometry columns."""
    params: list[object] = []
    assert _column_sql("name", params, "X", {}) == ("name", "$1")
    assert params == ["X"]

    params = []
    col, ph = _column_sql("status", params, "available", {"status": "public.equipment_status"})
    assert col == "status"
    assert ph == "$1::public.equipment_status"

    params = []
    col, ph = _column_sql("area_geojson", params, '{"type":"Polygon"}', {})
    assert col == "area_geom"
    assert ph == "extensions.ST_GeomFromGeoJSON($1)::geography"


def test_layer_specs_cover_all_types() -> None:
    """Every map_layer_type (and equipment) has an apply spec."""
    assert set(LAYER_SPECS) == {
        "hydrant",
        "evacuation_site",
        "risk_zone",
        "bodies_of_water",
        "underground_cistern",
        "equipment",
    }


# --------------------------------------------------------------------------- #
# Request schema validation
# --------------------------------------------------------------------------- #
def test_request_create_requires_target_for_mutation() -> None:
    """update/delete require target_id; create does not."""
    with pytest.raises(ValidationError):
        MapLayerRequestCreate(layer_type="hydrant", operation="update")
    with pytest.raises(ValidationError):
        MapLayerRequestCreate(layer_type="hydrant", operation="delete")
    created = MapLayerRequestCreate(
        layer_type="hydrant",
        operation="create",
        proposed_data={"latitude": 1.0, "longitude": 2.0},
    )
    assert created.target_id is None


# --------------------------------------------------------------------------- #
# Auth guards
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/equipment", None),
        ("post", "/equipment", {"organization_id": str(uuid4()), "name": "x"}),
        ("post", "/affiliates", {"organization_name": "x", "agency_type": "bfp"}),
        ("get", "/affiliates", None),
        ("get", "/map/hydrants", None),
        ("post", "/map/hydrants", {"latitude": 1.0, "longitude": 2.0}),
        ("post", f"/map/hydrants/{uuid4()}/ground-truth", {"status": "unknown"}),
        ("post", "/map-layer-requests", {"layer_type": "hydrant", "operation": "create"}),
        ("get", "/map-layer-requests/mine", None),
    ],
)
def test_phase12_endpoints_require_auth(
    client: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Phase 12 endpoints require a bearer token."""
    resp = (
        client.request(method, path, json=body)
        if body is not None
        else client.request(method, path)
    )
    assert resp.status_code == 401