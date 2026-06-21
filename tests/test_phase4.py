"""Phase 4 (KYC + email verification) endpoint guards + schema tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.admin import PendingVerification, VerificationReviewRequest


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/verification/national-id/start"),
        ("post", "/verification/national-id/refresh"),
        ("post", "/verification/email/request"),
        ("get", "/admin/verifications/pending"),
    ],
)
def test_phase4_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    """Phase 4 protected endpoints return 401 without a bearer token."""
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_verification_review_request_optional_notes() -> None:
    """VerificationReviewRequest notes is optional."""
    assert VerificationReviewRequest().notes is None
    assert VerificationReviewRequest(notes="blurry photo").notes == "blurry photo"


def test_pending_verification_requires_core_fields() -> None:
    """PendingVerification rejects construction without its required fields."""
    with pytest.raises(ValidationError):
        PendingVerification.model_validate({})