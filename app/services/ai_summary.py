"""Post-incident AI summary service (Section 3.6).

Gathers the structured facts of a closed incident, asks Claude Haiku for a
narrative post-incident report, and persists both to public.ai_summaries with
token and cost accounting. asyncpg has no JSON codec registered here, so jsonb is
dumped and loaded explicitly.

v11 changed what the facts are. The dispatch step is gone (Section 2.5), so "who
went" no longer comes from dispatch_logs — it comes from the team captain's
Post-Incident Report: the unit, driver, crew, equipment, notes and the
false-alarm flag. The facts also carry who accepted the incident, since under v11
the first Accept is what verified it and sent responders.

That is also why the summary is written when the report is filed rather than at
fire out: before then, the report — the most useful part of the record — does not
exist yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.anthropic_ai import AnthropicClient

log = get_logger(__name__)

# Agencies as coordinators and the BFP read them. Admin accepts carry no agency.
_AGENCY_NAME = {
    "fire_volunteer": "Fire Volunteers",
    "bfp": "BFP",
    "police": "Police",
    "medical": "Medical",
    "barangay": "Barangay",
}


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


def _jsonb(value: Any) -> Any:
    """asyncpg returns jsonb as text here; decode it, pass anything else through."""
    return json.loads(value) if isinstance(value, str) else value


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
        "Timeline:",
        f"  reported:     {ts['reported_at'] or '-'}",
        f"  accepted:     {ts['accepted_at'] or '-'}",
    ]
    # Only incidents that ran under v10 have one: v11 has no dispatch step.
    if ts.get("dispatched_at"):
        lines.append(f"  dispatched:   {ts['dispatched_at']}")
    lines += [
        f"  en route:     {ts['en_route_at'] or '-'}",
        f"  on scene:     {ts['arrived_at'] or '-'}",
        f"  fire out:     {ts['fire_out_at'] or '-'}",
        f"  report filed: {ts['closed_at'] or '-'}",
    ]

    if s["acceptances"]:
        lines.append("Accepted by:")
        for a in s["acceptances"]:
            who = _AGENCY_NAME.get(a["agency"] or "", "Admin")
            team = f" ({a['organization']})" if a["organization"] else ""
            # "Verified it" holds in both eras. Under v11 that same Accept also sent
            # responders, but under v10 dispatch was a separate step — so saying
            # "and sent responders" would be false for every incident from before
            # the migration. The timeline carries the rest.
            role = "first to accept; this verified it" if a["is_first"] else "also took part"
            lines.append(f"  - {who}{team}: {role}")
    else:
        lines.append("Accepted by: no acceptance recorded")

    lines.append(
        f"Neighbourhood corroboration: {nb['alerted']} alerted, "
        f"{nb['responded']} responded, {nb['confirmed']} confirmed a fire"
    )

    report = s["post_incident_report"]
    if report is None:
        lines.append("Post-Incident Report: not filed yet")
    else:
        filer = report["filed_by"] or "the team captain"
        agency = _AGENCY_NAME.get(report["filed_by_agency"] or "", "")
        lines.append(f"Post-Incident Report (filed by {filer}{', ' + agency if agency else ''}):")
        if report["false_alarm"]:
            lines.append(f"  FALSE ALARM — {report['false_alarm_note'] or 'no explanation given'}")
        lines.append(
            f"  Unit: {report['truck_label']} ({report['truck_type']}), "
            f"driver {report['driver_name']}"
        )
        crew = [
            f"{m['name']} ({m['role']})" if m.get("role") else m["name"]
            for m in report["roster"]
        ]
        lines.append(f"  Crew: {', '.join(crew) if crew else 'none recorded'}")
        equipment = report["equipment_taken"]
        lines.append(f"  Equipment taken: {', '.join(equipment) if equipment else 'none recorded'}")
        if report["notes"]:
            lines.append(f"  Captain's notes: {report['notes']}")

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
               a.arrived_at, a.resolved_at, a.closed_at
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
    acceptances = await db.fetch(
        """
        select x.agency::text as agency, o.name as org_name, x.is_first, x.accepted_at
        from public.area_acceptances x
        left join public.organizations o on o.id = x.organization_id
        where x.area_id = $1
        order by x.is_first desc, x.accepted_at asc
        """,
        area_id,
    )
    if not acceptances:
        # An incident verified under v10 has no area_acceptances row: v10 recorded
        # the decision as areas.verified_by, and the v11 migration only carried
        # over observer acknowledgements. Without this fallback the timeline would
        # say "accepted" while the facts said nobody had — and the model, told to
        # use only the facts, would be handed a contradiction.
        acceptances = await db.fetch(
            """
            select u.agency_type::text as agency, o.name as org_name,
                   true as is_first, a.verified_at as accepted_at
            from public.areas a
            join public.users u on u.id = a.verified_by
            left join public.organizations o on o.id = u.primary_org_id
            where a.id = $1 and a.verified_by is not null
            """,
            area_id,
        )
    report = await db.fetchrow(
        """
        select filed_by_name, filed_by_agency::text as filed_by_agency,
               truck_label, truck_type, driver_name, roster, equipment_taken,
               notes, false_alarm, false_alarm_note, submitted_at
        from public.post_incident_reports
        where area_id = $1
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
            # v11: verified_at is stamped by the first Accept (Section 2.5.1).
            "accepted_at": _iso(area["verified_at"]),
            "dispatched_at": _iso(area["dispatched_at"]),
            "en_route_at": _iso(area["en_route_at"]),
            "arrived_at": _iso(area["arrived_at"]),
            # The column kept its v10 name; the status it records is fire_out.
            "fire_out_at": _iso(area["resolved_at"]),
            "closed_at": _iso(area["closed_at"]),
        },
        "acceptances": [
            {
                "agency": a["agency"],
                "organization": a["org_name"],
                "is_first": a["is_first"],
                "accepted_at": _iso(a["accepted_at"]),
            }
            for a in acceptances
        ],
        "neighborhood": {
            "alerted": nb["alerted"] if nb else 0,
            "responded": nb["responded"] if nb else 0,
            "confirmed": nb["confirmed"] if nb else 0,
        },
        "post_incident_report": (
            None
            if report is None
            else {
                "filed_by": report["filed_by_name"],
                "filed_by_agency": report["filed_by_agency"],
                "truck_label": report["truck_label"],
                "truck_type": report["truck_type"],
                "driver_name": report["driver_name"],
                "roster": _jsonb(report["roster"]) or [],
                "equipment_taken": list(report["equipment_taken"] or []),
                "notes": report["notes"],
                "false_alarm": report["false_alarm"],
                "false_alarm_note": report["false_alarm_note"],
                "submitted_at": _iso(report["submitted_at"]),
            }
        ),
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


async def summarize_in_background(area_id: UUID) -> None:
    """Write the post-incident summary after the request that closed the incident.

    Runs once the Post-Incident Report is filed — the first moment every fact the
    summary needs exists. Scheduled as a background task so filing never waits on
    Claude, and it uses the shared pool rather than a request dependency because
    that request has already finished.

    Nothing here may surface as a failed filing: the incident is closed and the
    report stored either way. That also means a failure here is otherwise
    invisible, so a missing API key is logged as a warning rather than at info: when
    this was first checked, eight incidents had passed fire out and not one had a
    summary, and nothing anywhere had said so.
    """
    if not get_settings().anthropic_configured:
        log.warning("incident_summary_skipped", incident_id=str(area_id), reason="no_api_key")
        return
    try:
        await generate_incident_summary(database, AnthropicClient(), area_id)
        log.info("incident_summary_generated", incident_id=str(area_id))
    except Exception:
        log.error("incident_summary_failed", incident_id=str(area_id), exc_info=True)


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
