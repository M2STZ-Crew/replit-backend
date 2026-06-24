"""Phase 8 (neighborhood notifications) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.notification import NotificationRespondRequest


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def test_respond_schema_accepts_valid() -> None:
    """Both neighborhood responses ('report', 'ignore') validate and round-trip."""
    area_id = uuid4()
    for value in ("report", "ignore"):
        model = NotificationRespondRequest(area_id=area_id, response=value)
        assert model.area_id == area_id
        assert model.response == value


def test_respond_schema_rejects_bad_response() -> None:
    """A response outside the Report/Ignore enum is rejected."""
    with pytest.raises(ValidationError):
        NotificationRespondRequest(area_id=uuid4(), response="maybe")


def test_respond_schema_rejects_bad_area_id() -> None:
    """A non-UUID area_id is rejected."""
    with pytest.raises(ValidationError):
        NotificationRespondRequest(area_id="not-a-uuid", response="report")


def test_respond_requires_auth(client: TestClient) -> None:
    """POST /notifications/respond needs a bearer token (valid body, no auth -> 401)."""
    resp = client.post(
        "/notifications/respond",
        json={"area_id": str(uuid4()), "response": "ignore"},
    )
    assert resp.status_code == 401