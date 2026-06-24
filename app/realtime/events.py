"""Publish incident events to the WebSocket manager (Phase 10).

Status changes and dispatch updates fan out to the per-incident channel (clients
watching one incident) and to the relevant agency feeds (dashboards watching all
incidents for their agency, BFP<->Fire-Vol expanded two-way). Responder GPS fixes
fan out to the per-incident channel only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.realtime.manager import manager
from app.schemas.incident import IncidentDetail

_FIRE_AGENCIES = ("fire_volunteer", "bfp")


def _incident_agencies(detail: IncidentDetail) -> set[str]:
    """Agency channels relevant to an incident (BFP<->Fire-Vol expanded two-way)."""
    agencies: set[str] = set()
    for report in detail.reports:
        agencies.update(report.selected_agencies)
    if agencies & set(_FIRE_AGENCIES):
        agencies.update(_FIRE_AGENCIES)
    return agencies


async def broadcast_incident_event(detail: IncidentDetail, event_type: str) -> None:
    """Fan out an incident event to its incident channel and relevant agency feeds."""
    incident_id = str(detail.id)
    detail_json = detail.model_dump(mode="json")

    await manager.broadcast(
        f"incident:{incident_id}",
        {
            "type": event_type,
            "incident_id": incident_id,
            "status": detail.status,
            "incident": detail_json,
        },
    )

    feed: dict[str, Any] = {
        "type": "incident_feed",
        "event": event_type,
        "incident_id": incident_id,
        "designation": detail.designation,
        "status": detail.status,
        "alarm_level": detail.alarm_level,
        "active_dispatch_count": detail.active_dispatch_count,
    }
    for agency in _incident_agencies(detail):
        await manager.broadcast(f"agency:{agency}", feed)


async def broadcast_responder_location(
    incident_id: UUID, responder_id: UUID, location: dict[str, Any]
) -> None:
    """Fan out one responder GPS fix to the incident channel (live map)."""
    await manager.broadcast(
        f"incident:{incident_id}",
        {
            "type": "responder_location",
            "incident_id": str(incident_id),
            "responder_id": str(responder_id),
            **location,
        },
    )