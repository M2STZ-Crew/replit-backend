"""Crowdsourced neighborhood notification worker (Section 3.5).

Every 60 s, for each active area, pushes a Tagalog alert to registered users within
300 m of the centroid — excluding the area's reporters, users who already responded
(Report/Ignore), users at the 10-alert cap, and anyone alerted in the last 60 s — and
records per-(area, user) state. Stops automatically once an incident is resolved or
rejected (only active areas are processed).
"""

from __future__ import annotations

from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.fcm import PushService

log = get_logger(__name__)

_ALERT_TITLE = "Alerto sa Sunog"
_ALERT_BODY = (
    "May sunog ba sa lugar na ito? "
    "I-click ang notif na ito para makapag-submit ka rin ng report!"
)
_NEIGHBORHOOD_RADIUS_M = 300
_MAX_ALERTS = 10

_scheduler: AsyncIOScheduler | None = None


async def notify_area_neighbors(
    db: Database, push: PushService, area_id: UUID, lat: float, lng: float
) -> int:
    """Push the alert to eligible users near an area; return the number alerted."""
    point = f"SRID=4326;POINT({lng} {lat})"
    users = await db.fetch(
        f"""
        select u.id as user_id
        from public.users u
        where u.location is not null
          and extensions.ST_DWithin(
                u.location, extensions.ST_GeographyFromText($2), {_NEIGHBORHOOD_RADIUS_M})
          and exists (
              select 1 from public.device_tokens dt
              where dt.user_id = u.id and dt.is_active
          )
          and u.id not in (
              select r.reporter_id from public.area_reports ar
              join public.reports r on r.id = ar.report_id
              where ar.area_id = $1 and r.reporter_id is not null
          )
          and not exists (
              select 1 from public.neighborhood_notifications nn
              where nn.area_id = $1 and nn.user_id = u.id
                and (nn.response is not null
                     or nn.alerts_sent >= {_MAX_ALERTS}
                     or (nn.last_sent_at is not null
                         and nn.last_sent_at > now() - interval '60 seconds'))
          )
        """,
        area_id,
        point,
    )
    if not users:
        return 0
    user_ids = [u["user_id"] for u in users]

    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        user_ids,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if tokens:
        result = await push.send_to_tokens(
            tokens=tokens,
            title=_ALERT_TITLE,
            body=_ALERT_BODY,
            data={"type": "neighborhood_alert", "area_id": str(area_id)},
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )

    await db.execute(
        f"""
        insert into public.neighborhood_notifications (area_id, user_id, alerts_sent, last_sent_at)
        select $1, uid, 1, now() from unnest($2::uuid[]) as uid
        on conflict (area_id, user_id) do update
           set alerts_sent = least(
                   public.neighborhood_notifications.alerts_sent + 1, {_MAX_ALERTS}),
               last_sent_at = now()
        """,
        area_id,
        user_ids,
    )
    log.info("neighborhood_alerts_sent", area_id=str(area_id), users=len(user_ids))
    return len(user_ids)


async def neighborhood_tick() -> None:
    """Scheduled 60 s job: alert neighbors for every active area."""
    if not database.is_connected:
        return
    push = PushService()
    areas = await database.fetch(
        """
        select id, centroid_lat, centroid_lng
        from public.areas
        where status not in ('resolved', 'rejected')
        """
    )
    for area in areas:
        try:
            await notify_area_neighbors(
                database,
                push,
                area["id"],
                float(area["centroid_lat"]),
                float(area["centroid_lng"]),
            )
        except Exception:
            log.error("neighborhood_tick_failed", area_id=str(area["id"]), exc_info=True)


def start_neighborhood_scheduler() -> None:
    """Start the 60 s neighborhood-notification scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        neighborhood_tick,
        trigger="interval",
        seconds=60,
        id="neighborhood_notifications",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("neighborhood_scheduler_started")


def shutdown_neighborhood_scheduler() -> None:
    """Stop the scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("neighborhood_scheduler_stopped")