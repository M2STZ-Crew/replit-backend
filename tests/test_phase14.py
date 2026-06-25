"""Phase 14 (audit logging + PDF reports) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.audit import _safe_ip, match_audit_rule
from app.services.pdf_report import build_fire_out_pdf


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _facts() -> dict[str, Any]:
    """A representative structured-facts dict for the PDF builder."""
    return {
        "designation": "Area 1",
        "status": "resolved",
        "centroid": {"lat": 14.5, "lng": 120.9},
        "confidence": {"score": 0.8, "band": "high"},
        "report_count": 3,
        "alarm_level": "first_alarm",
        "timestamps": {
            k: None
            for k in (
                "reported_at",
                "verified_at",
                "dispatched_at",
                "en_route_at",
                "arrived_at",
                "resolved_at",
                "rejected_at",
            )
        },
        "neighborhood": {"alerted": 5, "responded": 2, "confirmed": 1},
        "dispatched_resources": [
            {
                "responder": "Juan",
                "organization": "BFP Pasay",
                "agency": "bfp",
                "type": "manual",
                "status": "completed",
                "dispatched_at": None,
            }
        ],
        "fire_codes": [{"code": "FC-1", "name": "Arrived", "pressed_at": None}],
    }


def test_match_audit_rule() -> None:
    """Curated paths map to actions/entities; others return None."""
    area_id = uuid4()
    matched = match_audit_rule("POST", f"/incidents/{area_id}/verify")
    assert matched is not None
    action, entity_type, entity_id, is_area = matched
    assert action == "incident.verify"
    assert entity_type == "area"
    assert entity_id == area_id
    assert is_area is True

    user_create = match_audit_rule("POST", "/admin/users")
    assert user_create is not None
    assert user_create[0] == "user.create"
    assert user_create[2] is None
    assert user_create[3] is False

    assert match_audit_rule("GET", "/incidents") is None
    assert match_audit_rule("POST", "/devices") is None


def test_safe_ip() -> None:
    """Only valid IP literals pass through; junk/None become None."""
    assert _safe_ip("127.0.0.1") == "127.0.0.1"
    assert _safe_ip("::1") == "::1"
    assert _safe_ip("testclient") is None
    assert _safe_ip(None) is None


def test_build_fire_out_pdf_returns_pdf_bytes() -> None:
    """The PDF builder returns a non-trivial PDF document."""
    data = build_fire_out_pdf(_facts(), "First paragraph.\n\nSecond paragraph.")
    assert isinstance(data, bytes)
    assert data[:5] == b"%PDF-"
    assert len(data) > 500


def test_build_fire_out_pdf_without_summary() -> None:
    """The PDF builds even with no AI summary."""
    assert build_fire_out_pdf(_facts(), None)[:5] == b"%PDF-"


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/audit-logs"),
        ("get", f"/incidents/{uuid4()}/report.pdf"),
    ],
)
def test_phase14_endpoints_require_auth(
    client: TestClient, method: str, path: str
) -> None:
    """The audit query and PDF endpoints require a bearer token."""
    assert client.request(method, path).status_code == 401