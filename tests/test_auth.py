"""Auth/verification/admin endpoint guards + schema validation tests.

Hermetic: the unauthenticated-access checks reject at the bearer dependency before
any DB/GoTrue/Twilio call, and the schema tests are pure Pydantic. The full
authenticated happy paths require a live Supabase and are exercised manually.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.admin import AdminCreateUserRequest
from app.schemas.verification import PhoneVerifyStartRequest


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/auth/me", None),
        ("post", "/verification/phone/request", {"phone": "+639171234567"}),
        ("post", "/verification/phone/verify", {"code": "123456"}),
        (
            "post",
            "/admin/users",
            {"email": "x@example.com", "password": "password123", "role": "general_user"},
        ),
    ],
)
def test_protected_endpoints_require_auth(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """Protected endpoints return 401 without a bearer token (valid bodies sent)."""
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_admin_create_requires_agency_for_subadmin() -> None:
    """sub_admin without agency_type is rejected by the schema validator."""
    with pytest.raises(ValidationError):
        AdminCreateUserRequest(email="x@example.com", password="password123", role="sub_admin")


def test_admin_create_rejects_agency_for_general_user() -> None:
    """general_user carrying an agency_type is rejected."""
    with pytest.raises(ValidationError):
        AdminCreateUserRequest(
            email="x@example.com",
            password="password123",
            role="general_user",
            agency_type="fire_volunteer",
        )


def test_admin_create_valid_subadmin() -> None:
    """A valid sub_admin + agency passes validation."""
    req = AdminCreateUserRequest(
        email="x@example.com",
        password="password123",
        role="sub_admin",
        agency_type="fire_volunteer",
    )
    assert req.role == "sub_admin"
    assert req.agency_type == "fire_volunteer"


def test_phone_request_rejects_non_e164() -> None:
    """A non-E.164 phone (missing +countrycode) is rejected."""
    with pytest.raises(ValidationError):
        PhoneVerifyStartRequest(phone="09171234567")


def test_phone_request_accepts_e164() -> None:
    """A valid E.164 phone is accepted."""
    assert PhoneVerifyStartRequest(phone="+639171234567").phone == "+639171234567"