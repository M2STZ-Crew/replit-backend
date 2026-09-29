"""Live responder tracking for citizens, and arrival on scene detected by GPS.

Responders' phones already stream a fix every few seconds while dispatched
(``POST /incidents/{id}/location`` or the socket's ``location`` frame), and
staff already watch those fixes on ``incident:<id>``. This module adds two
things on top of that same stream, without a second one:

- **Track It Live.** The citizen who reported an incident may follow it on
  ``track:<area_id>`` (or poll ``GET /areas/{id}/tracking``). What they receive
  is a :class:`TrackingSnapshot` — status, incident position, and per unit a
  label and a position — rebuilt from the database after each fix or status
  change, and only while someone is actually watching.

- **Automatic On scene.** When the incident is en route and a responder's last
  few fixes all put them within ``arrival_radius_meters`` of the incident, the
  status moves to arrived exactly as if they had pressed Arrived. Imprecise and
  old fixes do not count, so a bad GPS reading cannot declare arrival alone.
  The Arrived button stays; whichever comes first wins.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import Database
from app.realtime.manager import manager
from app.schemas.auth import AuthenticatedUser
from app.schemas.tracking import TrackedResponder, TrackingSnapshot
from app.services.incident import visible_agencies, visible_area_sql

log = get_logger(__name__)

# Statuses in which a citizen sees responders on the map. Before en route there
# is no one moving yet; after fire out the crews are done, and where they drive
# next is no business of the incident's.
TRACKED_STATUSES = ("en_route", "arrived")

_EARTH_RADIUS_M = 6_371_008.8


def track_channel(area_id: UUID) -> str:
    """The socket channel a citizen follows one incident on."""
    return f"track:{area_id}"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres; well within a metre at city scale."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- #
# Arrival
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Fix:
    """One stored GPS fix, as arrival detection needs it."""

    lat: float
    lng: float
    accuracy_m: float | None
    captured_at: datetime
    received_at: datetime


def arrival_distance(
    fixes: Sequence[Fix],
    centre: tuple[float, float],
    *,
    radius_m: float,
    needed: int,
    max_age_s: float,
    now: datetime,
) -> float | None:
    """Metres from ``centre`` if the newest ``needed`` fixes all say "arrived", else None.

    ``fixes`` is newest first. Every one of them must be:
    - inside the radius;
    - at least as precise as the radius (a fix that could be 300 m off proves
      nothing about 100 m; one with no accuracy at all proves nothing either);
    - fresh by the server's clock, and stamped by the phone within the same
      window of now — so a queue of old fixes sent late cannot declare arrival.
    """
    if needed < 1 or len(fixes) < needed:
        return None
    latest = fixes[:needed]
    for fix in latest:
        if (now - fix.received_at).total_seconds() > max_age_s:
            return None
        if abs((now - fix.captured_at).total_seconds()) > max_age_s:
            return None
        if fix.accuracy_m is None or fix.accuracy_m > radius_m:
            return None
        if haversine_m(fix.lat, fix.lng, centre[0], centre[1]) > radius_m:
            return None
    return haversine_m(latest[0].lat, latest[0].lng, centre[0], centre[1])


async def gps_arrival_distance(
    db: Database, area_id: UUID, responder_id: UUID, *, now: datetime | None = None
) -> float | None:
    """Whether this responder's GPS says they reached an en-route incident.

    Two small reads, and the second only while the incident is en route: this
    runs after every fix, so it must stay cheap for the other 99% of fixes.
    """
    settings = get_settings()
    area = await db.fetchrow(
        "select status::text as status, centroid_lat, centroid_lng "
        "from public.areas where id = $1",
        area_id,
    )
    if area is None or area["status"] != "en_route" or area["centroid_lat"] is None:
        return None
    rows = await db.fetch(
        """
        select lat, lng, accuracy_m, captured_at, created_at
        from public.responder_locations
        where responder_id = $1 and area_id = $2
        order by captured_at desc
        limit $3
        """,
        responder_id,
        area_id,
        settings.arrival_consecutive_fixes,
    )
    fixes = [
        Fix(
            lat=float(r["lat"]),
            lng=float(r["lng"]),
            accuracy_m=None if r["accuracy_m"] is None else float(r["accuracy_m"]),
            captured_at=r["captured_at"],
            received_at=r["created_at"],
        )
        for r in rows
    ]
    return arrival_distance(
        fixes,
        (float(area["centroid_lat"]), float(area["centroid_lng"])),
        radius_m=settings.arrival_radius_meters,
        needed=settings.arrival_consecutive_fixes,
        max_age_s=settings.responder_fix_max_age_seconds,
        now=now or datetime.now(UTC),
    )


# --------------------------------------------------------------------------- #
# Who may follow
# --------------------------------------------------------------------------- #
async def can_track(db: Database, user: AuthenticatedUser, area_id: UUID) -> bool:
    """Admin; staff who can see the incident; or a citizen who reported it.

    A citizen who did not report it gets the incident's public status through
    the map like everyone else, but not where the crews are.
    """
    if user.role == "admin":
        return True
    if user.role == "general_user":
        mine = await db.fetchval(
            """
            select exists (
                select 1 from public.area_reports ar
                join public.reports r on r.id = ar.report_id
                where ar.area_id = $1 and r.reporter_id = $2
            )
            """,
            area_id,
            user.id,
        )
        return bool(mine)
    agencies = visible_agencies(user)
    if not agencies:
        return False
    visible = await db.fetchval(
        f"select exists (select 1 from public.areas a where a.id = $1 and "
        f"{visible_area_sql(2)})",
        area_id,
        agencies,
    )
    return bool(visible)


# --------------------------------------------------------------------------- #
# The snapshot
# --------------------------------------------------------------------------- #
# Units are numbered by dispatch order across every dispatch of the incident,
# withdrawn ones included, so Unit 2 stays Unit 2 when Unit 1 goes home. Each
# unit's latest fix comes from the (responder, captured_at) index.
_UNITS_SQL = """
with units as (
    select d.responder_id, d.vehicle_name, d.status::text as status,
           o.name as org_name,
           coalesce(o.agency_type::text, u.agency_type::text) as agency,
           row_number() over (order by d.dispatched_at, d.id) as unit_no
    from public.dispatch_logs d
    join public.users u on u.id = d.responder_id
    left join public.organizations o
           on o.id = coalesce(d.organization_id, u.primary_org_id)
    where d.area_id = $1
)
select un.unit_no, un.vehicle_name, un.org_name, un.agency,
       f.lat, f.lng, f.heading_deg, f.speed_mps, f.accuracy_m,
       f.created_at as received_at
from units un
left join lateral (
    select rl.lat, rl.lng, rl.heading_deg, rl.speed_mps, rl.accuracy_m, rl.created_at
    from public.responder_locations rl
    where rl.responder_id = un.responder_id and rl.area_id = $1
    order by rl.captured_at desc
    limit 1
) f on true
where un.status = 'active'
order by un.unit_no
"""


def units_from_rows(
    rows: Sequence[Any], *, now: datetime, stale_after_s: float
) -> list[TrackedResponder]:
    """Turn dispatch rows into the units a citizen sees.

    The crew of one truck each carry a phone, and each phone streams; a citizen
    should see one truck, not four dots on top of each other. Dispatches naming
    the same vehicle become one unit, shown at the freshest of its crew's fixes.
    A responder without a vehicle is a unit of their own.
    """
    groups: dict[str, list[Any]] = {}
    for row in rows:
        vehicle = (row["vehicle_name"] or "").strip()
        group = f"v:{vehicle.casefold()}" if vehicle else f"u:{row['unit_no']}"
        groups.setdefault(group, []).append(row)

    units: list[tuple[int, TrackedResponder]] = []
    for members in groups.values():
        number = min(int(m["unit_no"]) for m in members)
        with_fix = [m for m in members if m["received_at"] is not None]
        best = max(with_fix, key=lambda m: m["received_at"]) if with_fix else members[0]
        vehicle = (best["vehicle_name"] or "").strip()
        received = best["received_at"]
        stale = received is None or (now - received).total_seconds() > stale_after_s
        units.append(
            (
                number,
                TrackedResponder(
                    key=f"unit-{number}",
                    label=vehicle or f"Unit {number}",
                    organization=best["org_name"],
                    agency=best["agency"],
                    lat=None if best["lat"] is None else round(float(best["lat"]), 6),
                    lng=None if best["lng"] is None else round(float(best["lng"]), 6),
                    heading_deg=best["heading_deg"],
                    speed_mps=best["speed_mps"],
                    accuracy_m=best["accuracy_m"],
                    updated_at=received,
                    stale=stale,
                ),
            )
        )
    return [unit for _, unit in sorted(units, key=lambda pair: pair[0])]


async def build_tracking_snapshot(
    db: Database, area_id: UUID, *, now: datetime | None = None
) -> TrackingSnapshot | None:
    """The current Track It Live picture for one incident, or None if it does not exist."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    area = await db.fetchrow(
        "select id, designation, status::text as status, centroid_lat, centroid_lng "
        "from public.areas where id = $1",
        area_id,
    )
    if area is None:
        return None
    responders: list[TrackedResponder] = []
    if area["status"] in TRACKED_STATUSES:
        rows = await db.fetch(_UNITS_SQL, area_id)
        responders = units_from_rows(
            rows, now=now, stale_after_s=settings.tracking_stale_after_seconds
        )
    return TrackingSnapshot(
        area_id=area["id"],
        designation=area["designation"],
        status=area["status"],
        centroid_lat=area["centroid_lat"],
        centroid_lng=area["centroid_lng"],
        arrival_radius_m=settings.arrival_radius_meters,
        stale_after_seconds=settings.tracking_stale_after_seconds,
        responders=responders,
        generated_at=now,
    )


async def publish_tracking(db: Database, area_id: UUID) -> int:
    """Send a fresh snapshot to whoever follows ``area_id``; return how many got it.

    Nothing is read when nobody is watching, which is almost always: this runs
    after every responder fix. Never raises — a tracking hiccup must not fail
    the fix or the status change that triggered it.
    """
    channel = track_channel(area_id)
    if manager.channel_size(channel) == 0:
        return 0
    try:
        snapshot = await build_tracking_snapshot(db, area_id)
        if snapshot is None:
            return 0
        return await manager.broadcast(
            channel, {"type": "tracking", "snapshot": snapshot.model_dump(mode="json")}
        )
    except Exception:
        log.error("tracking_publish_failed", area_id=str(area_id), exc_info=True)
        return 0
