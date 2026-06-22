"""Phase 7 (area clustering) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.clustering import _designation
from app.services.geo import haversine_m


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def test_designation_versions() -> None:
    """Designations: 'Area N' for v1, 'Area N.V' for later versions."""
    assert _designation(1, 1) == "Area 1"
    assert _designation(3, 2) == "Area 3.2"
    assert _designation(5, 4) == "Area 5.4"


def test_haversine_known_distance() -> None:
    """~0.0036 deg latitude is ~400 m (matches the overlap test geometry)."""
    assert 380 < haversine_m(14.6, 121.0, 14.6036, 121.0) < 420


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/areas"),
        ("get", f"/areas/{uuid4()}"),
        ("get", "/areas/overlaps/pending"),
        ("post", f"/areas/overlaps/{uuid4()}/merge"),
        ("post", f"/areas/overlaps/{uuid4()}/keep-separate"),
    ],
)
def test_area_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    """Area + overlap endpoints require authentication."""
    assert client.request(method, path).status_code == 401