"""Phase 11 (Claude Haiku AI summaries) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_summary import _iso, _render_facts, _row_to_dict


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _structured(**overrides: Any) -> dict[str, Any]:
    """Build a representative structured-facts dict."""
    base: dict[str, Any] = {
        "designation": "Area 7",
        "status": "resolved",
        "centroid": {"lat": 14.5, "lng": 120.9},
        "confidence": {"score": 0.82, "band": "high"},
        "report_count": 4,
        "alarm_level": "first_alarm",
        "timestamps": {
            "reported_at": "2026-06-23T08:00:00+00:00",
            "verified_at": "2026-06-23T08:05:00+00:00",
            "dispatched_at": None,
            "en_route_at": None,
            "arrived_at": None,
            "resolved_at": "2026-06-23T08:40:00+00:00",
            "rejected_at": None,
        },
        "neighborhood": {"alerted": 6, "responded": 3, "confirmed": 2},
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
        "fire_codes": [{"code": "C-1", "name": "Water supply", "pressed_at": None}],
    }
    base.update(overrides)
    return base


def test_iso_handles_none_and_datetime() -> None:
    """_iso passes through None and ISO-formats aware datetimes."""
    assert _iso(None) is None
    dt = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)
    assert _iso(dt) == dt.isoformat()


def test_render_facts_includes_key_sections() -> None:
    """The rendered facts mention the incident, alarm, neighbors, resources, codes."""
    text = _render_facts(_structured())
    assert "Area 7" in text
    assert "first_alarm" in text
    assert "6 alerted" in text
    assert "Juan" in text
    assert "BFP Pasay" in text
    assert "C-1" in text


def test_render_facts_empty_sections() -> None:
    """Empty resources / codes / alarm render explicit 'none' lines."""
    text = _render_facts(
        _structured(alarm_level=None, dispatched_resources=[], fire_codes=[])
    )
    assert "Alarm level: none" in text
    assert "Dispatched resources: none recorded" in text
    assert "Fire codes activated: none" in text


def test_row_to_dict_parses_jsonb_and_cost() -> None:
    """A jsonb string is parsed to a dict and numeric cost coerced to float."""
    out = _row_to_dict({"structured_report": '{"a": 1}', "cost_usd": Decimal("0.001234")})
    assert out["structured_report"] == {"a": 1}
    assert isinstance(out["cost_usd"], float)
    assert out["cost_usd"] == pytest.approx(0.001234)


def test_row_to_dict_handles_nulls() -> None:
    """Null jsonb and cost pass through as None."""
    out = _row_to_dict({"structured_report": None, "cost_usd": None})
    assert out["structured_report"] is None
    assert out["cost_usd"] is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"/incidents/{uuid4()}/summary"),
        ("get", f"/incidents/{uuid4()}/summaries"),
    ],
)
def test_ai_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    """The AI summary endpoints require a bearer token."""
    assert client.request(method, path).status_code == 401