"""Incident-domain logic: agency visibility, lifecycle state machine, GPS persistence.

Kept separate from the route module so the dispatch, responder-GPS, and WebSocket
layers share the same visibility rule, status guards, and location writer.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
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

# Statuses nothing leaves (v10 Section 2.5). 'merged' is terminal for the
# absorbed area only — its reports were moved onto the surviving area (Section
# 2.3). 'closed' is reached only by filing the Post-Incident Report.
TERMINAL_STATUSES = ("rejected", "merged", "closed")

# Statuses that take an area out of the live feed: it must not cluster new
# reports, alert neighbors, or count as an active incident. Wider than
# TERMINAL_STATUSES because fire out ends the response before the paperwork is
# done — a resolved area waits in 'post_incident_report' (the captain's
# "pending report" tray) without being live.
OFF_FEED_STATUSES = ("resolved", "post_incident_report", *TERMINAL_STATUSES)

# Statuses that additionally bar an area from seeding a 1 h version chain.
# The post-fire statuses are deliberately absent: a genuine second fire at the
# same location within the hour is exactly what "Area 1.2" designates (Section
# 2.3). A rejected area was never an incident, and a merged one was absorbed.
UNVERSIONABLE_STATUSES = ("rejected", "merged")

# Allowed forward transitions of public.area_status (Section 2.5). Mirrors the DB
# sequencing CHECK constraints: dispatched needs verified, en_route needs
# dispatched, arrived needs en_route, post_incident_report needs resolved, closed
# needs post_incident_report. Resolve is reachable from any active state once
# verified; reject only before responders are committed. Merge is only legal
# before responders are committed — after dispatch it would orphan their
# assignments. 'resolved' only ever moves on to the report step, and 'closed' is
# additionally pinned by a trigger to the existence of a filed report.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"verified", "rejected", "merged"},
    "verified": {"dispatched", "resolved", "rejected", "merged"},
    "dispatched": {"en_route", "resolved"},
    "en_route": {"arrived", "resolved"},
    "arrived": {"resolved"},
    "resolved": {"post_incident_report"},
    "post_incident_report": {"closed"},
    "closed": set(),
    "rejected": set(),
    "merged": set(),
}


def _status_exclusion_sql(statuses: tuple[str, ...], alias: str) -> str:
    """Render ``[alias.]status not in (...)`` for a tuple of area_status values."""
    prefix = f"{alias}." if alias else ""
    values = ", ".join(f"'{status}'" for status in statuses)
    return f"{prefix}status not in ({values})"


def active_area_sql(alias: str = "") -> str:
    """SQL predicate restricting ``public.areas`` to live incidents.

    Single source of truth for every query that filters the active feed — clustering,
    overlap detection, the neighborhood worker, and both read routes — so a status
    added to the enum can't be handled in some of them and missed in others.
    ``alias`` qualifies the column when the query joins areas under a table alias.
    """
    return _status_exclusion_sql(OFF_FEED_STATUSES, alias)


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


def visible_area_sql(agencies_param: int, alias: str = "a") -> str:
    """SQL predicate: the area has a member report that asked for one of the agencies.

    ``agencies_param`` is the positional parameter holding the agency list. This
    is the whole of incident visibility (Section 2.6.1): an agency sees the areas
    a reporter asked it to, BFP and Fire Volunteer see each other's.
    """
    return (
        "exists (select 1 from public.area_reports ar "
        "join public.reports r on r.id = ar.report_id "
        f"where ar.area_id = {alias}.id "
        f"and r.selected_agencies && ${agencies_param}::public.agency_type[])"
    )


async def assert_incident_visible(
    db: Database, incident_id: UUID, user: AuthenticatedUser
) -> str:
    """Return the incident's status, or raise 404 (missing) / 403 (not your agency's)."""
    status_val = await db.fetchval(
        "select status::text from public.areas where id = $1", incident_id
    )
    if status_val is None:
        raise NotFoundError("Incident not found.")
    agencies = visible_agencies(user)
    if agencies is None:
        return str(status_val)
    visible = bool(agencies) and await db.fetchval(
        f"select {visible_area_sql(2)} from public.areas a where a.id = $1",
        incident_id,
        agencies,
    )
    if not visible:
        raise ForbiddenError("This incident is not visible to your agency.")
    return str(status_val)


def routable_agencies(requested: set[str] | list[str]) -> set[str]:
    """Agencies Admin may route an incident to, given what its reporters requested.

    Routing follows the report (v10 Section 2.6.2), so an agency nobody asked for
    is not routable — that keeps visibility scoped by selected_agencies. The fire
    agencies count as one request, as they do for visibility: the SOS screen
    offers "fire", and BFP already sees every Fire Volunteer incident.
    """
    agencies = set(requested)
    if agencies & set(_FIRE_AGENCIES):
        agencies |= set(_FIRE_AGENCIES)
    return agencies


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


def assert_team_captain(user: AuthenticatedUser) -> None:
    """Raise 403 unless the user may file a Post-Incident Report (v10 Section 2.5).

    The responding team captain files — a sub-admin of a coordinating (fire)
    agency, on behalf of everyone who went. Response Team members do not file
    individually, an observer agency has no truck or crew on the fireground, and
    Admin routes incidents rather than captaining a team.
    """
    if user.role == "sub_admin" and user.agency_type in COORDINATING_AGENCIES:
        return
    if is_observer(user):
        raise ForbiddenError(
            "Your agency takes part for situational awareness only, so it cannot "
            "file a Post-Incident Report. The responding Fire Volunteer or BFP team "
            "captain files it.",
            details={"agency_type": user.agency_type, "access": "observer"},
        )
    raise ForbiddenError(
        "Only the responding team captain (a Fire Volunteer or BFP sub-admin) files "
        "the Post-Incident Report."
    )


def assert_can_accept(user: AuthenticatedUser) -> None:
    """Raise 403 unless the user may press Accept on a routed incident (Section 2.6.1).

    Accept is the observer-side action. Coordinators do not see it — they verify
    and dispatch instead — and Admin is the one doing the routing.
    """
    if is_observer(user):
        return
    raise ForbiddenError(
        "Accept is how an observer agency acknowledges an incident routed to it. "
        "Coordinators verify and dispatch instead."
    )


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