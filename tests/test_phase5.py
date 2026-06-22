"""Phase 5 (device tokens / FCM) endpoint guards + schema tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.device import DeviceTokenCreate


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/devices", {"fcm_token": "tok-1234567890", "platform": "android"}),
        ("get", "/devices", None),
        ("post", "/devices/test", None),
    ],
)
def test_device_endpoints_require_auth(
    client: TestClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    """Device endpoints return 401 without a bearer token."""
    response = client.request(method, path, json=body)
    assert response.status_code == 401


def test_device_token_create_rejects_bad_platform() -> None:
    """An unsupported platform is rejected by the schema."""
    with pytest.raises(ValidationError):
        DeviceTokenCreate(fcm_token="t" * 20, platform="symbian")  # type: ignore[arg-type]


def test_device_token_create_valid() -> None:
    """A valid token + platform passes validation."""
    dt = DeviceTokenCreate(fcm_token="t" * 20, platform="android")
    assert dt.platform == "android"