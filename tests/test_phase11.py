"""Phase 11 (Claude Haiku AI summaries) unit + guard tests (hermetic).

Nothing here calls Anthropic: the client is exercised against a stand-in for
AsyncAnthropic, so the tests cost nothing and run without a key.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import incidents, post_incident_reports
from app.core.exceptions import ExternalServiceError
from app.integrations import anthropic_ai
from app.integrations.anthropic_ai import AnthropicClient
from app.main import app
from app.services.ai_summary import _iso, _render_facts, _row_to_dict


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _report(**overrides: Any) -> dict[str, Any]:
    """A filed Post-Incident Report, as gather_incident_facts shapes it."""
    base: dict[str, Any] = {
        "filed_by": "Ana Reyes",
        "filed_by_agency": "fire_volunteer",
        "truck_label": "Apollo",
        "truck_type": "Fire truck",
        "driver_name": "Juan Dela Cruz",
        "roster": [
            {"name": "Juan Dela Cruz", "role": "Driver"},
            {"name": "Maria Santos", "role": "Nozzle"},
        ],
        "equipment_taken": ["2.5in hose x3", "SCBA x2"],
        "notes": "Hydrant on Taft was dry; drew from the tanker.",
        "false_alarm": False,
        "false_alarm_note": None,
        "submitted_at": "2026-06-23T09:10:00+00:00",
    }
    base.update(overrides)
    return base


def _structured(**overrides: Any) -> dict[str, Any]:
    """A representative v11 structured-facts dict for a closed incident."""
    base: dict[str, Any] = {
        "designation": "Area 7",
        "status": "closed",
        "centroid": {"lat": 14.5, "lng": 120.9},
        "confidence": {"score": 0.82, "band": "high"},
        "report_count": 4,
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
        "acceptances": [
            {
                "agency": "fire_volunteer",
                "organization": "Hercules Fire Brigade",
                "is_first": True,
                "accepted_at": "2026-06-23T08:02:00+00:00",
            },
            {
                "agency": "medical",
                "organization": None,
                "is_first": False,
                "accepted_at": "2026-06-23T08:04:00+00:00",
            },
        ],
        "neighborhood": {"alerted": 6, "responded": 3, "confirmed": 2},
        "post_incident_report": _report(),
        "fire_codes": [{"code": "C-1", "name": "Water supply", "pressed_at": None}],
    }
    base.update(overrides)
    return base


def test_iso_handles_none_and_datetime() -> None:
    """_iso passes through None and ISO-formats aware datetimes."""
    assert _iso(None) is None
    dt = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)
    assert _iso(dt) == dt.isoformat()


# --------------------------------------------------------------------------- #
# The facts the model is given (v11)
# --------------------------------------------------------------------------- #
def test_render_facts_includes_key_sections() -> None:
    """The incident, its acceptance, the neighbours, the report and the codes."""
    text = _render_facts(_structured())
    assert "Area 7" in text
    assert "first_alarm" in text
    assert "6 alerted" in text
    assert "Hercules Fire Brigade" in text
    assert "C-1" in text


def test_the_crew_comes_from_the_post_incident_report() -> None:
    """v11: who went is the captain's record, not a dispatch log (Section 2.5.3)."""
    text = _render_facts(_structured())
    assert "Apollo (Fire truck)" in text
    assert "driver Juan Dela Cruz" in text
    assert "Maria Santos (Nozzle)" in text
    assert "SCBA x2" in text
    assert "Hydrant on Taft was dry" in text


def test_the_v10_vocabulary_is_gone() -> None:
    """No dispatch step, no dispatch log, no 'resolved' — v11 removed all three."""
    text = _render_facts(_structured())
    assert "Dispatched resources" not in text
    assert "dispatched:" not in text
    assert "resolved" not in text
    assert "fire out:" in text
    assert "report filed:" in text


def test_the_first_accept_is_told_apart_from_participation() -> None:
    """The first Accept verified the incident; later ones only joined it (2.5.1)."""
    text = _render_facts(_structured())
    assert "Fire Volunteers (Hercules Fire Brigade): first" in text
    assert "Medical: also took part" in text


def test_an_admin_accept_is_named_as_admin() -> None:
    """Admin accounts carry no agency, so an Admin Accept must still read sensibly."""
    text = _render_facts(
        _structured(
            acceptances=[
                {"agency": None, "organization": None, "is_first": True, "accepted_at": None}
            ]
        )
    )
    assert "Admin: first" in text


def test_a_false_alarm_leads_the_report_with_its_explanation() -> None:
    """Section 2.5.3: the flag is the headline, and it never appears unexplained."""
    text = _render_facts(
        _structured(
            post_incident_report=_report(
                false_alarm=True, false_alarm_note="Rubbish fire, already out on arrival."
            )
        )
    )
    report_section = text.split("Post-Incident Report")[1]
    assert report_section.index("FALSE ALARM") < report_section.index("Unit:")
    assert "Rubbish fire, already out on arrival." in text


def test_an_unfiled_report_says_so() -> None:
    """A manual summary before filing must not pretend the report exists."""
    text = _render_facts(_structured(post_incident_report=None, status="post_incident_report"))
    assert "Post-Incident Report: not filed yet" in text
    assert "Unit:" not in text


def test_a_v10_incident_keeps_its_real_dispatch_time() -> None:
    """Incidents that ran before v11 genuinely have one; it stays in their history."""
    ts = dict(_structured()["timestamps"], dispatched_at="2026-06-23T08:03:00+00:00")
    text = _render_facts(_structured(timestamps=ts))
    assert "dispatched:   2026-06-23T08:03:00+00:00" in text


def test_render_facts_empty_sections() -> None:
    """Missing acceptances, crew, equipment, codes and alarm render explicit lines."""
    text = _render_facts(
        _structured(
            alarm_level=None,
            acceptances=[],
            fire_codes=[],
            post_incident_report=_report(roster=[], equipment_taken=[], notes=None),
        )
    )
    assert "Alarm level: none" in text
    assert "Accepted by: no acceptance recorded" in text
    assert "Crew: none recorded" in text
    assert "Equipment taken: none recorded" in text
    assert "Captain's notes" not in text
    assert "Fire codes activated: none" in text


# --------------------------------------------------------------------------- #
# The client: what it sends, and what it refuses to store
# --------------------------------------------------------------------------- #
def _message(stop_reason: str, text: str = "Area 7 was reported at 08:00.") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=320,
            output_tokens=180,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        _request_id="req_test",
    )


class _FakeAnthropic:
    """Stands in for AsyncAnthropic: records the request, returns a fixed message."""

    def __init__(self, message: Any) -> None:
        self._message = message
        self.sent: dict[str, Any] = {}
        self.messages = self

    async def __aenter__(self) -> _FakeAnthropic:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def create(self, **kwargs: Any) -> Any:
        self.sent = kwargs
        return self._message


def _client_with(monkeypatch: pytest.MonkeyPatch, message: Any) -> tuple[AnthropicClient, Any]:
    fake = _FakeAnthropic(message)
    monkeypatch.setattr(anthropic_ai, "AsyncAnthropic", lambda **_kw: fake)
    summarizer = AnthropicClient()
    summarizer._settings = SimpleNamespace(  # type: ignore[assignment]
        anthropic_configured=True,
        anthropic_api_key="test-key",
        anthropic_model="claude-haiku-4-5",
        anthropic_max_tokens=1024,
    )
    return summarizer, fake


async def test_a_truncated_summary_is_refused_not_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report cut off at max_tokens reads as complete once stored, so it is not."""
    summarizer, _ = _client_with(monkeypatch, _message("max_tokens"))
    with pytest.raises(ExternalServiceError, match="cut off"):
        await summarizer.summarize_incident("facts")


async def test_a_refusal_is_not_stored_as_a_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summarizer, _ = _client_with(monkeypatch, _message("refusal", text=""))
    with pytest.raises(ExternalServiceError, match="declined"):
        await summarizer.summarize_incident("facts")


async def test_a_finished_summary_is_returned_with_its_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summarizer, _ = _client_with(monkeypatch, _message("end_turn"))
    result = await summarizer.summarize_incident("facts")
    assert result.summary_text == "Area 7 was reported at 08:00."
    assert result.total_tokens == 500
    # Haiku 4.5: 320 input at $1/M plus 180 output at $5/M.
    assert result.cost_usd == pytest.approx(0.00122)


async def test_the_system_prompt_carries_no_cache_breakpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Haiku 4.5 caches only 4,096+ token prefixes; this one is ~200, so none."""
    summarizer, fake = _client_with(monkeypatch, _message("end_turn"))
    await summarizer.summarize_incident("facts")
    assert isinstance(fake.sent["system"], str)
    assert "cache_control" not in str(fake.sent)


# --------------------------------------------------------------------------- #
# When the summary is written
# --------------------------------------------------------------------------- #
def test_fire_out_no_longer_schedules_the_summary() -> None:
    """At fire out the Post-Incident Report does not exist yet."""
    assert "background" not in inspect.signature(incidents.resolve_incident).parameters


def test_filing_the_report_schedules_the_summary() -> None:
    """Filing is the first moment every fact the summary needs is on record."""
    route = post_incident_reports.file_post_incident_report
    assert "background" in inspect.signature(route).parameters
    assert "summarize_in_background" in inspect.getsource(route)


# --------------------------------------------------------------------------- #
# Stored rows and auth
# --------------------------------------------------------------------------- #
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
