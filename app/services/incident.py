"""Incident-domain logic: agency visibility, lifecycle state machine, GPS persistence.

Kept separate from the route module so the dispatch, responder-GPS, and WebSocket
layers share the same visibility rule, status guards, and location writer.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import ResponderLocationCreate

# BFP and Fire Volunteers see each other's fire incidents (Section 6, two-way).
_FIRE_AGENCIES = ("fire_volunteer", "bfp")

# Allowed forward transitions of public.area_status (Section 9). Mirrors the DB
# sequencing CHECK constraints: dispatched needs verified, en_route needs
# dispatched, arrived needs en_route. Resolve is reachable from any active state
# once verified; reject only before responders are committed.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"verified", "rejected"},
    "verified": {"dispatched", "resolved", "rejected"},
    "dispatched": {"en_route", "resolved"},
    "en_route": {"arrived", "resolved"},
    "arrived": {"resolved"},
    "resolved": set(),
    "rejected": set(),
}


def visible_agencies(user: AuthenticatedUser) -> list[str] | None:
    """Agencies whose incidents this user may see; ``None`` means all (admin)."""
    if user.role == "admin":
        return None
    if user.agency_type in _FIRE_AGENCIES:
        return list(_FIRE_AGENCIES)
    if user.agency_type:
        return [user.agency_type]
    return []


def assert_transition(current: str, target: str) -> None:
    """Raise 409 if ``current -> target`` is not an allowed lifecycle transition."""
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"Cannot move an incident from '{current}' to '{target}'.",
            details={
                "current_status": current,
                "target_status": target,
                "allowed": sorted(ALLOWED_TRANSITIONS.get(current, set())),
            },
        )


async def record_responder_location(
    db: Database,
    incident_id: UUID,
    responder_id: UUID,
    payload: ResponderLocationCreate,
) -> bool:
    """Persist a GPS fix iff the responder has an active dispatch here; True if recorded."""
    active_id = await db.fetchval(
        """
        select id from public.dispatch_logs
        where area_id = $1 and responder_id = $2 and status = 'active'
        order by dispatched_at desc
        limit 1
        """,
        incident_id,
        responder_id,
    )
    if active_id is None:
        return False
    await db.execute(
        """
        insert into public.responder_locations
            (responder_id, area_id, dispatch_id, lat, lng, accuracy_m, speed_mps,
             heading_deg, captured_at)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        responder_id,
        incident_id,
        payload.dispatch_id or active_id,
        payload.lat,
        payload.lng,
        payload.accuracy_m,
        payload.speed_mps,
        payload.heading_deg,
        payload.captured_at,
    )
    return True