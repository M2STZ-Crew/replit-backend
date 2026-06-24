"""Post-incident AI summary service (Phase 11, Section 3.6).

Gathers the structured facts of a resolved incident (designation, centroid, the 7
lifecycle timestamps, neighborhood corroboration, dispatched resources, fire-code
activations), asks Claude Haiku for a narrative fire-out report, and persists both
to public.ai_summaries with token + cost accounting. asyncpg has no JSON codec
registered here, so jsonb is dumped/loaded explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.exceptions import NotFoundError
from app.db.session import Database
from app.integrations.anthropic_ai import AnthropicClient


def _iso(value: datetime | None) -> str | None:
    """ISO-format a timestamp, or None."""
    return value.isoformat() if value is not None else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Normalize an ai_summaries row: parse jsonb, coerce numeric cost to float."""
    data = dict(row)
    report = data.get("structured_report")
    data["structured_report"] = json.loads(report) if isinstance(report, str) else report
    cost = data.get("cost_usd")
    data["cost_usd"] = float(cost) if cost is not None else None
    return data


@dataclass(frozen=True)
class IncidentFacts:
    """Structured incident facts plus a human-readable rendering for the model."""

    structured: dict[str, Any]
    facts_text: str


def _render_facts(s: dict[str, Any]) -> str:
    """Render the structured facts into a compact text block for the model."""
    ts = s["timestamps"]
    nb = s["neighborhood"]
    lines = [
        f"Incident: {s['designation']} (status: {s['status']})",
        f"Location (centroid): lat {s['centroid']['lat']}, lng {s['centroid']['lng']}",
        f"Confidence: {s['confidence']['score']} ({s['confidence']['band']}), "
        f"from {s['report_count']} citizen report(s)",
        f"Alarm level: {s['alarm_level'] or 'none'}",
        "Lifecycle timestamps:",
        f"  reported:   {ts['reported_at'] or '-'}",
        f"  verified:   {ts['verified_at'] or '-'}",
        f"  dispatched: {ts['dispatched_at'] or '-'}",
        f"  en route:   {ts['en_route_at'] or '-'}",
        f"  arrived:    {ts['arrived_at'] or '-'}",
        f"  resolved:   {ts['resolved_at'] or '-'}",
        f"  rejected:   {ts['rejected_at'] or '-'}",
        f"Neighborhood corroboration: {nb['alerted']} alerted, "
        f"{nb['responded']} responded, {nb['confirmed']} confirmed a fire",
    ]
    if s["dispatched_resources"]:
        lines.append("Dispatched resources:")
        for d in s["dispatched_resources"]:
            who = d["responder"] or "Unknown responder"
            org = f" ({d['organization']})" if d["organization"] else ""
            lines.append(f"  - {who}{org} [{d['type']}, {d['status']}]")
    else:
        lines.append("Dispatched resources: none recorded")
    if s["fire_codes"]:
        lines.append("Fire codes activated:")
        for c in s["fire_codes"]:
            lines.append(f"  - {c['code']} {c['name']}")
    else:
        lines.append("Fire codes activated: none")
    return "\n".join(lines)


async def gather_incident_facts(db: Database, area_id: UUID) -> IncidentFacts:
    """Collect the structured facts for an incident; raise 404 if it does not exist."""
    area = await db.fetchrow(
        """
        select a.designation, a.status::text as status,
               a.centroid_lat, a.centroid_lng, a.report_count,
               a.confidence_score, a.confidence_band::text as confidence_band,
               a.alarm_level::text as alarm_level,
               a.reported_at, a.verified_at, a.dispatched_at, a.en_route_at,
               a.arrived_at, a.resolved_at, a.rejected_at
        from public.areas a
        where a.id = $1
        """,
        area_id,
    )
    if area is None:
        raise NotFoundError("Incident not found.")

    nb = await db.fetchrow(
        """
        select count(*) as alerted,
               count(*) filter (where response is not null) as responded,
               count(*) filter (where response = 'report') as confirmed
        from public.neighborhood_notifications
        where area_id = $1
        """,
        area_id,
    )
    dispatches = await db.fetch(
        """
        select d.dispatch_type::text as dispatch_type, d.status::text as status,
               u.full_name as responder_name,
               o.name as org_name, o.agency_type::text as org_agency,
               d.dispatched_at
        from public.dispatch_logs d
        left join public.users u on u.id = d.responder_id
        left join public.organizations o on o.id = d.organization_id
        where d.area_id = $1
        order by d.dispatched_at asc
        """,
        area_id,
    )
    fire_codes = await db.fetch(
        """
        select fc.code_number, fc.name, e.pressed_at
        from public.fire_code_events e
        join public.fire_codes fc on fc.id = e.fire_code_id
        where e.area_id = $1
        order by e.pressed_at asc
        """,
        area_id,
    )

    structured: dict[str, Any] = {
        "designation": area["designation"],
        "status": area["status"],
        "centroid": {"lat": area["centroid_lat"], "lng": area["centroid_lng"]},
        "confidence": {"score": area["confidence_score"], "band": area["confidence_band"]},
        "report_count": area["report_count"],
        "alarm_level": area["alarm_level"],
        "timestamps": {
            "reported_at": _iso(area["reported_at"]),
            "verified_at": _iso(area["verified_at"]),
            "dispatched_at": _iso(area["dispatched_at"]),
            "en_route_at": _iso(area["en_route_at"]),
            "arrived_at": _iso(area["arrived_at"]),
            "resolved_at": _iso(area["resolved_at"]),
            "rejected_at": _iso(area["rejected_at"]),
        },
        "neighborhood": {
            "alerted": nb["alerted"] if nb else 0,
            "responded": nb["responded"] if nb else 0,
            "confirmed": nb["confirmed"] if nb else 0,
        },
        "dispatched_resources": [
            {
                "responder": d["responder_name"],
                "organization": d["org_name"],
                "agency": d["org_agency"],
                "type": d["dispatch_type"],
                "status": d["status"],
                "dispatched_at": _iso(d["dispatched_at"]),
            }
            for d in dispatches
        ],
        "fire_codes": [
            {
                "code": c["code_number"],
                "name": c["name"],
                "pressed_at": _iso(c["pressed_at"]),
            }
            for c in fire_codes
        ],
    }
    return IncidentFacts(structured=structured, facts_text=_render_facts(structured))


async def generate_incident_summary(
    db: Database, client: AnthropicClient, area_id: UUID
) -> dict[str, Any]:
    """Gather facts, call Claude, persist to ai_summaries, and return the stored row."""
    facts = await gather_incident_facts(db, area_id)
    result = await client.summarize_incident(facts.facts_text)
    row = await db.fetchrow(
        """
        insert into public.ai_summaries
            (area_id, model, prompt, prompt_tokens, completion_tokens, cached_tokens,
             total_tokens, cost_usd, summary_text, structured_report, anthropic_request_id)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
        returning id, area_id, model, summary_text, structured_report,
                  prompt_tokens, completion_tokens, cached_tokens, total_tokens,
                  cost_usd, anthropic_request_id, generated_at
        """,
        area_id,
        result.model,
        facts.facts_text,
        result.prompt_tokens,
        result.completion_tokens,
        result.cached_tokens,
        result.total_tokens,
        result.cost_usd,
        result.summary_text,
        json.dumps(facts.structured),
        result.request_id,
    )
    assert row is not None
    return _row_to_dict(row)


async def list_incident_summaries(db: Database, area_id: UUID) -> list[dict[str, Any]]:
    """Return all stored summaries for an incident, newest first."""
    rows = await db.fetch(
        """
        select id, area_id, model, summary_text, structured_report,
               prompt_tokens, completion_tokens, cached_tokens, total_tokens,
               cost_usd, anthropic_request_id, generated_at
        from public.ai_summaries
        where area_id = $1
        order by generated_at desc
        """,
        area_id,
    )
    return [_row_to_dict(r) for r in rows]