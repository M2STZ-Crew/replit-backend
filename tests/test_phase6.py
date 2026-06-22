"""Phase 6 (incident reporting) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes.reports import _parse_agencies
from app.core.exceptions import BadRequestError
from app.main import app
from app.services.exif import extract_gps, validate_image
from app.services.geo import haversine_m


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (12, 8), "blue").save(buf, format="PNG")
    return buf.getvalue()


def test_haversine_zero_and_known() -> None:
    """Haversine is 0 for the same point and ~111 m per 0.001 deg latitude."""
    assert haversine_m(14.5, 120.9, 14.5, 120.9) == 0.0
    assert 105 < haversine_m(14.5, 120.9, 14.501, 120.9) < 116


def test_validate_image_ok() -> None:
    """A valid PNG returns its dimensions."""
    assert validate_image(_png_bytes()) == (12, 8)


def test_validate_image_rejects_garbage() -> None:
    """Non-image bytes are rejected."""
    with pytest.raises(BadRequestError):
        validate_image(b"this is not an image")


def test_extract_gps_none_without_exif() -> None:
    """An image without EXIF GPS yields None (the NO-EXIF case)."""
    assert extract_gps(_png_bytes()) is None


def test_parse_agencies_valid() -> None:
    """Valid agencies parse to a clean list."""
    assert _parse_agencies("fire_volunteer, bfp") == ["fire_volunteer", "bfp"]


def test_parse_agencies_invalid() -> None:
    """An unknown agency is rejected."""
    with pytest.raises(BadRequestError):
        _parse_agencies("fire_volunteer,space_force")


def test_reports_mine_requires_auth(client: TestClient) -> None:
    """GET /reports/mine requires a bearer token."""
    assert client.get("/reports/mine").status_code == 401