"""Phase 13 (fire codes, alarm requests) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.alarm_requests import _is_bfp_subadmin
from app.main import app
from app.schemas.alarm import AlarmRequestCreate
from app.schemas.auth import AuthenticatedUser
from app.schemas.fire_code import FireCodePressRequest


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _user(role: str, agency: str | None = None) -> AuthenticatedUser:
    """Build a minimal AuthenticatedUser."""
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency)


def test_is_bfp_subadmin() -> None:
    """Only a BFP sub-admin is the alarm execution authority."""
    assert _is_bfp_subadmin(_user("sub_admin", "bfp")) is True
    assert _is_bfp_subadmin(_user("sub_admin", "fire_volunteer")) is False
    assert _is_bfp_subadmin(_user("admin")) is False
    assert _is_bfp_subadmin(_user("response_team", "bfp")) is False


def test_alarm_request_validates_level() -> None:
    """Only the alarm-ladder enum values are accepted."""
    with pytest.raises(ValidationError):
        AlarmRequestCreate(area_id=uuid4(), requested_alarm_level="mega_alarm")
    model = AlarmRequestCreate(area_id=uuid4(), requested_alarm_level="general_alarm")
    assert model.requested_alarm_level == "general_alarm"


def test_fire_code_press_area_is_optional() -> None:
    """A fire-code press can be standalone or tied to an incident."""
    assert FireCodePressRequest().area_id is None
    tied = FireCodePressRequest(area_id=uuid4(), notes="arrived")
    assert tied.notes == "arrived"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/fire-codes", None),
        ("get", "/fire-codes/events", None),
        ("post", f"/fire-codes/{uuid4()}/press", {}),
        (
            "post",
            "/alarm-requests",
            {"area_id": str(uuid4()), "requested_alarm_level": "first_alarm"},
        ),
        ("get", "/alarm-requests/mine", None),
        ("get", "/alarm-requests", None),
        ("post", f"/alarm-requests/{uuid4()}/execute", {}),
        ("post", f"/alarm-requests/{uuid4()}/reject", {}),
    ],
)
def test_phase13_endpoints_require_auth(
    client: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Phase 13 endpoints require a bearer token."""
    resp = (
        client.request(method, path, json=body)
        if body is not None
        else client.request(method, path)
    )
    assert resp.status_code == 401