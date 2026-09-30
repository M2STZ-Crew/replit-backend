"""Phase 11 (DeepSeek AI summaries) unit + guard tests (hermetic).

Nothing here calls DeepSeek: the client is pointed at an httpx MockTransport,
so the tests cost nothing and run without a key.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import incidents, post_incident_reports
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.integrations.deepseek_ai import DeepSeekClient, DeepSeekNotConfiguredError
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
        "incident_at": "2026-06-23T08:00:00+00:00",
        "fire_out_at": "2026-06-23T08:40:00+00:00",
        "units": [
            {"name": "Apollo", "type": "Fire Truck"},
            {"name": "Hermes", "type": "Fire Truck"},
        ],
        "truck_label": "Apollo, Hermes",
        "truck_type": "Fire Truck",
        "driver_name": "Juan Dela Cruz",
        "roster": [{"name": "Juan Dela Cruz"}, {"name": "Maria Santos"}],
        "equipment_taken": ["Hose line", "SCBA"],
        "notes": None,
        "false_alarm": False,
        "false_alarm_note": None,
        "submitted_at": "2026-06-23T09:10:00+00:00",
    }
    base.update(overrides)
    return base


def _structured(**overrides: Any) -> dict[str, Any]:
    """A representative structured-facts dict for a closed incident."""
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
# The facts the model is given
# --------------------------------------------------------------------------- #
def test_render_facts_includes_key_sections() -> None:
    """The incident, its acceptance, the neighbours, the report and the codes."""
    text = _render_facts(_structured())
    assert "Area 7" in text
    assert "first_alarm" in text
    assert "6 alerted" in text
    assert "Hercules Fire Brigade" in text
    assert "C-1" in text


def test_the_summary_is_given_what_the_captain_selected() -> None:
    """The report's six answers are what the model reads: the two times, every
    unit, the driver, the roster and the equipment (Section 2.5.3)."""
    text = _render_facts(_structured())
    assert "Time of the incident: 2026-06-23T08:00:00+00:00" in text
    assert "Time the fire was out: 2026-06-23T08:40:00+00:00" in text
    assert "Units: Apollo (Fire Truck), Hermes (Fire Truck)" in text
    assert "Driver: Juan Dela Cruz" in text
    assert "Crew: Juan Dela Cruz, Maria Santos" in text
    assert "Equipment taken: Hose line, SCBA" in text


def test_a_report_from_before_roles_were_dropped_still_names_them() -> None:
    text = _render_facts(
        _structured(post_incident_report=_report(roster=[{"name": "Maria", "role": "Nozzle"}]))
    )
    assert "Maria (Nozzle)" in text


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
            post_incident_report=_report(false_alarm=True, false_alarm_note="Fire already out")
        )
    )
    report_section = text.split("Post-Incident Report")[1]
    assert report_section.index("FALSE ALARM") < report_section.index("Units:")
    assert "Fire already out" in text


def test_an_unfiled_report_says_so() -> None:
    """A manual summary before filing must not pretend the report exists."""
    text = _render_facts(_structured(post_incident_report=None, status="post_incident_report"))
    assert "Post-Incident Report: not filed yet" in text
    assert "Units:" not in text


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
            post_incident_report=_report(units=[], roster=[], equipment_taken=[]),
        )
    )
    assert "Alarm level: none" in text
    assert "Accepted by: no acceptance recorded" in text
    assert "Units: none recorded" in text
    assert "Crew: none recorded" in text
    assert "Equipment taken: none recorded" in text
    assert "Captain's notes" not in text
    assert "Fire codes activated: none" in text


# --------------------------------------------------------------------------- #
# The client: what it sends DeepSeek, and what it refuses to store
# --------------------------------------------------------------------------- #
def _completion(finish: str = "stop", text: str = "Area 7 was reported at 08:00.") -> dict:
    return {
        "id": "cmpl-test",
        "choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}],
        "usage": {
            "prompt_tokens": 320,
            "completion_tokens": 180,
            "total_tokens": 500,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 320,
        },
    }


def _client_with(
    body: dict[str, Any] | None = None, *, status: int = 200, model: str = "deepseek-flash"
) -> tuple[DeepSeekClient, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json=body if body is not None else _completion())

    summarizer = DeepSeekClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    summarizer._settings = SimpleNamespace(  # type: ignore[assignment]
        deepseek_configured=True,
        deepseek_summarization="test-key",
        deepseek_model=model,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_max_tokens=1024,
    )
    return summarizer, sent


def test_the_key_is_read_from_deepseek_summarization() -> None:
    """The setting is named as the key is named on the host and in .env."""
    assert "deepseek_summarization" in Settings.model_fields
    assert Settings(deepseek_summarization="k").deepseek_configured is True
    assert Settings(deepseek_summarization="").deepseek_configured is False
    assert "anthropic_api_key" not in Settings.model_fields


async def test_it_asks_deepseek_with_thinking_off() -> None:
    summarizer, sent = _client_with()
    await summarizer.summarize_incident("the facts")

    request = sent[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-flash"
    assert body["max_tokens"] == 1024
    # On by default, and it would spend the output budget reasoning.
    assert body["thinking"] == {"type": "disabled"}
    assert body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "the facts"


async def test_a_truncated_summary_is_refused_not_stored() -> None:
    """A report cut off at max_tokens reads as complete once stored, so it is not."""
    summarizer, _ = _client_with(_completion("length"))
    with pytest.raises(ExternalServiceError, match="cut off"):
        await summarizer.summarize_incident("facts")


async def test_a_filtered_answer_is_not_stored_as_a_summary() -> None:
    summarizer, _ = _client_with(_completion("content_filter", text=""))
    with pytest.raises(ExternalServiceError, match="declined"):
        await summarizer.summarize_incident("facts")


async def test_an_interrupted_answer_is_not_stored_either() -> None:
    summarizer, _ = _client_with(_completion("insufficient_system_resource"))
    with pytest.raises(ExternalServiceError, match="did not finish"):
        await summarizer.summarize_incident("facts")


@pytest.mark.parametrize("status", [401, 402, 429, 500])
async def test_a_refused_request_is_one_plain_failure(status: int) -> None:
    """Wrong key, no balance, rate limit, their outage: the log says which."""
    summarizer, _ = _client_with({"error": {"message": "nope"}}, status=status)
    with pytest.raises(ExternalServiceError, match="request failed"):
        await summarizer.summarize_incident("facts")


async def test_a_finished_summary_is_returned_with_its_cost() -> None:
    summarizer, _ = _client_with()
    result = await summarizer.summarize_incident("facts")
    assert result.summary_text == "Area 7 was reported at 08:00."
    assert result.model == "deepseek-flash"
    assert result.total_tokens == 500
    assert result.request_id == "cmpl-test"
    # deepseek-flash at peak rates: 320 input at $0.30/M plus 180 output at $1.20/M.
    assert result.cost_usd == pytest.approx(0.000312)


async def test_an_unpriced_model_has_no_cost_rather_than_a_wrong_one() -> None:
    summarizer, _ = _client_with(model="deepseek-something-new")
    result = await summarizer.summarize_incident("facts")
    assert result.cost_usd is None


async def test_without_a_key_it_says_so() -> None:
    summarizer, sent = _client_with()
    summarizer._settings.deepseek_configured = False
    with pytest.raises(DeepSeekNotConfiguredError):
        await summarizer.summarize_incident("facts")
    assert sent == []


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
