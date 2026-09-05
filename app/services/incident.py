"""Incident-domain logic: agency visibility, lifecycle state machine, GPS persistence.

Kept separate from the route module so the dispatch, responder-GPS, and WebSocket
layers share the same visibility rule, status guards, and location writer.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError, ForbiddenError
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import ResponderLocationCreate

# BFP and Fire Volunteers see each other's fire incidents (Section 6, two-way).
_FIRE_AGENCIES = ("fire_volunteer", "bfp")

# Agencies that may change an incident's state. The two fire agencies coordinate
# the response, so their sub-admins verify, reject, resolve and dispatch.
COORDINATING_AGENCIES = _FIRE_AGENCIES

# Every other agency a reporter can summon — police, medical, barangay — takes
# part for situational awareness only (Section 1.3 problem 9, cross-agency
# silos). Their sub-admins see incidents that requested their agency and nothing
# else: they must not be able to reject someone else's fire, resolve it, dispatch
# Fire Volunteers, or press fire codes.
OBSERVER_AGENCIES = ("police", "medical", "barangay")

# Statuses that take an area out of the live feed. 'merged' is terminal for the
# absorbed area only — its reports were moved onto the surviving area, so it must
# not cluster, alert neighbors, or appear as an incident (Section 3.4).
TERMINAL_STATUSES = ("resolved", "rejected", "merged")

# Statuses that additionally bar an area from seeding a 1 h version chain.
# 'resolved' is deliberately absent: a genuine second fire at the same location
# within the hour is exactly what "Area 1.2" designates (Section 3.4). A rejected
# area was never an incident, and a merged one was absorbed elsewhere.
UNVERSIONABLE_STATUSES = ("rejected", "merged")

# Allowed forward transitions of public.area_status (Section 9). Mirrors the DB
# sequencing CHECK constraints: dispatched needs verified, en_route needs
# dispatched, arrived needs en_route. Resolve is reachable from any active state
# once verified; reject only before responders are committed. Merge is only legal
# before responders are committed — after dispatch it would orphan their assignments.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"verified", "rejected", "merged"},
    "verified": {"dispatched", "resolved", "rejected", "merged"},
    "dispatched": {"en_route", "resolved"},
    "en_route": {"arrived", "resolved"},
    "arrived": {"resolved"},
    "resolved": set(),
    "rejected": set(),
    "merged": set(),
}


def _status_exclusion_sql(statuses: tuple[str, ...], alias: str) -> str:
    """Render ``[alias.]status not in (...)`` for a tuple of area_status values."""
    prefix = f"{alias}." if alias else ""
    values = ", ".join(f"'{status}'" for status in statuses)
    return f"{prefix}status not in ({values})"


def active_area_sql(alias: str = "") -> str:
    """SQL predicate restricting ``public.areas`` to non-terminal (live) incidents.

    Single source of truth for every query that filters the active feed — clustering,
    overlap detection, the neighborhood worker, and both read routes — so a status
    added to the enum can't be handled in some of them and missed in others.
    ``alias`` qualifies the column when the query joins areas under a table alias.
    """
    return _status_exclusion_sql(TERMINAL_STATUSES, alias)


def versionable_area_sql(alias: str = "") -> str:
    """SQL predicate for areas eligible to seed a 1 h version chain (Section 3.4).

    Looser than :func:`active_area_sql` by design — see ``UNVERSIONABLE_STATUSES``.
    """
    return _status_exclusion_sql(UNVERSIONABLE_STATUSES, alias)


def visible_agencies(user: AuthenticatedUser) -> list[str] | None:
    """Agencies whose incidents this user may see; ``None`` means all (admin)."""
    if user.role == "admin":
        return None
    if user.agency_type in _FIRE_AGENCIES:
        return list(_FIRE_AGENCIES)
    if user.agency_type:
        return [user.agency_type]
    return []


def is_coordinator(user: AuthenticatedUser) -> bool:
    """True when the user may change an incident's state.

    Admin keeps full authority as the system owner. Among sub-admins only the
    fire agencies coordinate; an observer sub-admin (police, medical, barangay)
    is read-only on incidents no matter which one requested their agency.
    """
    if user.role == "admin":
        return True
    return user.role == "sub_admin" and user.agency_type in COORDINATING_AGENCIES


def is_observer(user: AuthenticatedUser) -> bool:
    """True for a sub-admin whose agency only observes (police, medical, barangay)."""
    return user.role == "sub_admin" and user.agency_type in OBSERVER_AGENCIES


def assert_coordinator(user: AuthenticatedUser, action: str) -> None:
    """Raise 403 unless the user may change incident state.

    The message names the caller's own agency rather than saying "forbidden", so
    a Barangay sub-admin who taps something understands they are an observer
    rather than assuming the system is broken.
    """
    if is_coordinator(user):
        return
    if is_observer(user):
        raise ForbiddenError(
            f"Your agency takes part for situational awareness only, so it cannot "
            f"{action}. Fire Volunteer or BFP coordinators handle this.",
            details={"agency_type": user.agency_type, "access": "observer"},
        )
    raise ForbiddenError(f"You do not have permission to {action}.")


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