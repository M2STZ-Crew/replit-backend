"""Crowdsourced neighborhood notification worker (Section 3.5).

Every 60 s, for each active area, pushes an alert — in each user's language
(citizen_copy.NEIGHBOUR_ALERT: Tagalog, or English) — to registered users whose
last known location is within 150 m of the centroid (PRD v13/v14 §4.2: 300 m dragged
in too many unrelated households in dense Pasay) and was reported within the last
NEIGHBORHOOD_LOCATION_MAX_AGE_MINUTES (30): a location the phone sent hours ago is
where they were, not where they are (5 Nov 2026, issue list 2.2) — excluding the area's reporters,
users who already responded (Report/Ignore), users at the 10-alert cap, and anyone
alerted in the last 60 s — and records per-(area, user) state. Stops automatically
once an incident is resolved or rejected (only active areas are processed).
"""

from __future__ import annotations

from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.fcm import PushService, SoundCategory
from app.services.citizen_copy import NEIGHBOUR_ALERT, Language, by_language, language_of
from app.services.incident import active_area_sql
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

# The Tagalog alert PRD v14 §4.2 was written with; residents who read the app in
# English get NEIGHBOUR_ALERT["en"].
_ALERT_TITLE, _ALERT_BODY = NEIGHBOUR_ALERT["tl"]
# Nobody farther than this from the fire is alerted (PRD v14 §4.2, §4.13.3).
NEIGHBORHOOD_RADIUS_M = 150
_MAX_ALERTS = 10

_scheduler: AsyncIOScheduler | None = None


async def notify_area_neighbors(
    db: Database, push: PushService, area_id: UUID, lat: float, lng: float
) -> int:
    """Push the alert to eligible users near an area; return the number alerted."""
    point = f"SRID=4326;POINT({lng} {lat})"
    max_age = get_settings().neighborhood_location_max_age_minutes
    users = await db.fetch(
        f"""
        select u.id as user_id,
               u.language,
               exists (
                   select 1 from public.neighborhood_notifications nn
                   where nn.area_id = $1 and nn.user_id = u.id and nn.alerts_sent > 0
               ) as alerted_before
        from public.users u
        where u.location is not null
          and u.location_updated_at > now() - make_interval(mins => $4::int)
          and extensions.ST_DWithin(
                u.location, extensions.ST_GeographyFromText($2), $3::double precision)
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
        NEIGHBORHOOD_RADIUS_M,
        max_age,
    )
    if not users:
        return 0
    user_ids = [u["user_id"] for u in users]

    # The first alert plays the fire recording; the reminders after it (one a
    # minute, up to ten, until they answer) play the citizen recording and
    # replace the last one in the shade — ten sirens would teach people to mute
    # the app. Each in the language the resident reads the app in.
    languages: dict[UUID, Language] = {
        u["user_id"]: language_of(u.get("language")) for u in users
    }
    first = {u["user_id"]: languages[u["user_id"]] for u in users if not u["alerted_before"]}
    again = {u["user_id"]: languages[u["user_id"]] for u in users if u["alerted_before"]}
    sounds: tuple[tuple[dict[UUID, Language], SoundCategory], ...] = (
        (first, "fire"),
        (again, "citizen"),
    )
    for group, sound in sounds:
        for language, ids in by_language(group).items():
            await _push_alert(db, push, area_id, ids, sound=sound, language=language)

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
    for language, ids in by_language(languages).items():
        title, body = NEIGHBOUR_ALERT[language]
        await record_inbox(db, ids, "fire_alert", title, body, {"area_id": str(area_id)})
    log.info("neighborhood_alerts_sent", area_id=str(area_id), users=len(user_ids))
    return len(user_ids)


async def _push_alert(
    db: Database,
    push: PushService,
    area_id: UUID,
    user_ids: list[UUID],
    *,
    sound: SoundCategory,
    language: Language = "tl",
) -> None:
    """Push the neighbourhood alert to these users' phones; retire dead tokens."""
    title, body = NEIGHBOUR_ALERT[language]
    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        user_ids,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if not tokens:
        return
    result = await push.send_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "neighborhood_alert", "area_id": str(area_id)},
        sound=sound,
        tag=f"nearby-{area_id}",
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )


async def neighborhood_tick() -> None:
    """Scheduled 60 s job: alert neighbors for every active area."""
    if not database.is_connected:
        return
    push = PushService()
    areas = await database.fetch(
        f"""
        select id, centroid_lat, centroid_lng
        from public.areas
        where {active_area_sql()}
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