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


def _pdf_text(data: bytes) -> str:
    """The text drawn in an uncompressed reportlab PDF - what a reader sees."""
    import re

    chunks = re.findall(rb"\((.*?)(?<!\\)\)\s*Tj", data, re.S)
    return " ".join(
        c.decode("latin-1").replace("\\(", "(").replace("\\)", ")") for c in chunks
    )


def _facts(*, report: bool = True) -> dict[str, Any]:
    """Facts in the shape gather_incident_facts really builds (v11 onwards).

    The builder used to be tested against a hand-made dict with a
    "dispatched_resources" list, which the real facts stopped carrying in v11 -
    so the tests passed while the endpoint failed on every incident.
    """
    return {
        "designation": "Area 1",
        "status": "closed",
        "centroid": {"lat": 14.5, "lng": 120.9},
        "confidence": {"score": 0.8, "band": "high"},
        "report_count": 3,
        "alarm_level": "first_alarm",
        "timestamps": {
            "reported_at": "2026-06-23T08:00:00+00:00",
            "accepted_at": "2026-06-23T08:02:00+00:00",
            "dispatched_at": None,
            "en_route_at": "2026-06-23T08:02:00+00:00",
            "arrived_at": "2026-06-23T08:11:00+00:00",
            "fire_out_at": "2026-06-23T08:40:00+00:00",
            "closed_at": "2026-06-23T09:10:00+00:00",
        },
        "acceptances": [],
        "neighborhood": {"alerted": 5, "responded": 2, "confirmed": 1},
        "post_incident_reports": (
            [{
                "filed_by": "Ramon Dizon",
                "filed_by_agency": "fire_volunteer",
                "organization": "Hercules Fire Brigade",
                "incident_at": "2026-06-23T08:00:00+00:00",
                "fire_out_at": "2026-06-23T08:40:00+00:00",
                "units": [
                    {"name": "Apollo", "type": "Fire Truck"},
                    {"name": "Hermes", "type": "Fire Truck"},
                ],
                "truck_label": "Apollo, Hermes",
                "truck_type": "Fire Truck",
                "driver_name": "Paolo Villareal",
                "roster": [{"name": "Paolo Villareal"}, {"name": "Jericho Manalo"}],
                "equipment_taken": ["Hose line", "SCBA"],
                "notes": None,
                "false_alarm": False,
                "false_alarm_note": None,
                "submitted_at": "2026-06-23T09:10:00+00:00",
            }]
            if report
            else []
        ),
        "fire_codes": [{"code": "FC-1", "name": "Arrived", "pressed_at": None}],
    }


def test_match_audit_rule() -> None:
    """Curated paths map to actions/entities; others return None."""
    request_id = uuid4()
    matched = match_audit_rule("POST", f"/alarm-requests/{request_id}/execute")
    assert matched is not None
    action, entity_type, entity_id, is_area = matched
    assert action == "alarm.execute"
    assert entity_type == "alarm_request"
    assert entity_id == request_id
    assert is_area is False

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


def test_build_fire_out_pdf_before_the_report_is_filed() -> None:
    """Fire out, report still owed: the PDF says so rather than failing."""
    assert build_fire_out_pdf(_facts(report=False), None)[:5] == b"%PDF-"


def test_the_pdf_lists_every_teams_report() -> None:
    """Two teams filed: the report has a subsection for each, in filing order."""
    facts = _facts()
    second = dict(
        facts["post_incident_reports"][0],
        filed_by="Arnel Robles",
        filed_by_agency="bfp",
        organization="BFP Pasay City Fire Station",
        driver_name="Dennis Cabrera",
    )
    facts["post_incident_reports"].append(second)
    flat = _pdf_text(
        build_fire_out_pdf(facts, "Summary.", summary_model="deepseek-flash", compress=False)
    )
    assert "Fire Incident Report" in flat
    assert "5.1" in flat and "Hercules Fire Brigade" in flat
    assert "5.2" in flat and "BFP Pasay City Fire Station" in flat
    assert flat.index("Paolo Villareal") < flat.index("Dennis Cabrera")
    # Philippine time, not the UTC the facts are stored in.
    assert "23 Jun 2026, 4:40 PM" in flat
    assert "Written by AI (deepseek-flash)" in flat


def test_the_pdf_is_built_from_the_facts_the_summary_uses() -> None:
    """The two must not drift: both read gather_incident_facts' output."""
    from tests.test_phase11 import _structured

    assert build_fire_out_pdf(_structured(), "Summary.")[:5] == b"%PDF-"


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