"""The citizen map, live: one channel every signed-in user may follow.

The map draws what GET /areas returns. ``map:areas`` tells it when that
changed, so it changes on screen within a second instead of on the next
15-second read: a new incident appears, a status moves on, a report joins, an
alarm is raised, an incident ends and leaves the map.

What a message carries is exactly one AreaSummary row — the same columns GET
/areas already gives every signed-in user, read by the same SELECT — plus
whether the incident is still on the live map. No reports, no reporters, no
responders: nothing the map did not already show.

Every call site runs after its change is committed, and publishing never
raises, so a socket hiccup can never fail the report, status change or merge
that triggered it. Nothing is read when nobody is watching.
"""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.realtime.manager import manager
from app.schemas.area import AreaSummary
from app.services.incident import active_area_sql

log = get_logger(__name__)

MAP_CHANNEL = "map:areas"

# The columns of AreaSummary. GET /areas selects these too, so the map's first
# read and every message after it describe an area identically.
AREA_SUMMARY_COLS = """
    id, designation, status::text as status, centroid_lat, centroid_lng,
    report_count, confidence_score, confidence_band::text as confidence_band,
    alarm_level::text as alarm_level, reported_at, updated_at
"""


async def publish_area_change(db: Database, area_id: UUID) -> int:
    """Tell everyone watching the map that ``area_id`` changed; return how many heard.

    ``active`` false means the incident left the live map (fire out, closed,
    rejected, merged) and the app should take it off.
    """
    if manager.channel_size(MAP_CHANNEL) == 0:
        return 0
    try:
        row = await db.fetchrow(
            f"select {AREA_SUMMARY_COLS}, ({active_area_sql()}) as active "
            "from public.areas where id = $1",
            area_id,
        )
        if row is None:
            return 0
        data = dict(row)
        active = bool(data.pop("active"))
        area = AreaSummary.model_validate(data)
        return await manager.broadcast(
            MAP_CHANNEL,
            {
                "type": "area",
                "channel": MAP_CHANNEL,
                "active": active,
                "area": area.model_dump(mode="json"),
            },
        )
    except Exception:
        log.error("map_publish_failed", area_id=str(area_id), exc_info=True)
        return 0
