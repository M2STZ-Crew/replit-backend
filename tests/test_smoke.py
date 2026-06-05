"""Smoke tests for the Phase 1 scaffold.

Verifies the application boots and the public meta/health endpoints respond with the
expected payloads, correlation headers, and structured error envelope. These run
fully in-process via FastAPI's TestClient — no network, database, or external
services required.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """Provide a TestClient bound to the app, running startup/shutdown lifespan."""
    with TestClient(app) as test_client:
        yield test_client


def test_root_returns_service_info(client: TestClient) -> None:
    """GET / returns service metadata with the expected fields."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "RepLiT Backend"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "development"
    assert body["docs_url"] == "/docs"
    assert body["health_url"] == "/health"


def test_health_returns_ok(client: TestClient) -> None:
    """GET /health returns a healthy liveness payload."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "RepLiT Backend"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "development"


def test_readiness_returns_ready(client: TestClient) -> None:
    """GET /health/ready reports readiness with an (empty) checks map."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {}


def test_request_id_header_generated(client: TestClient) -> None:
    """Every response carries a generated X-Request-ID correlation header."""
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) == 32  # uuid4().hex


def test_request_id_is_echoed_when_provided(client: TestClient) -> None:
    """A client-supplied X-Request-ID is propagated back on the response."""
    supplied = "test-correlation-id-123"
    response = client.get("/health", headers={"X-Request-ID": supplied})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == supplied


def test_unknown_route_returns_structured_404(client: TestClient) -> None:
    """Unknown routes return the standard ErrorResponse envelope (404)."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "http_404"
    assert "message" in body
    assert "request_id" in body