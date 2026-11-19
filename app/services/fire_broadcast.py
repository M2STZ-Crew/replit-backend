"""Every resident hears of a verified fire (v1.12.38).

18 Nov 2026: "even outside of 100m everyone get notified (but in the 100m can
only corroborate)", and "Everyone, once verified". Once staff verify a fire
(reported -> verified), every resident with RepLiT on a phone gets one alert,
in the language they read the app in, that opens the fire's details. Waiting
for the verification keeps a false report from alarming the whole city.

Left out: the residents within 100 m with a fresh location, who are asked "Do
you see it too?" instead and are the only ones who can corroborate
(app/workers/neighborhood.py); the fire's own reporters, who hear of it
already; and accounts frozen for deletion. The verify step happens once per
fire, so this goes once.

v1.12.42 (18 Nov 2026: "create a placeholder for voice for far incidents
(outside 100m). and remain the sound of near incident"): this alert has a
voice of its own, in English or Tagalog (res/raw/sound_far_en and
sound_far_tl, on app v1.12.53's channels), and says the fire's street.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, far_voice, has_far_voice, token_versions
from app.services.citizen_copy import by_language, fire_verified, language_of
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

# The neighbourhood alert's radius (app/workers/neighborhood.py).
CORROBORATION_RADIUS_M = 100
# FCM takes at most 500 tokens per multicast.
_BATCH = 500

# Sent after the verify answers, so the coordinator does not wait on it; kept
# here so the task is not collected mid-way.
_running: set[asyncio.Task[Any]] = set()


def spawn(job: Coroutine[Any, Any, Any]) -> None:
    """Run [job] after the request, logging rather than raising."""

    async def guarded() -> None:
        try:
            await job
        except Exception:
            log.error("fire_broadcast_failed", exc_info=True)

    task = asyncio.create_task(guarded())
    _running.add(task)
    task.add_done_callback(_running.discard)


async def notify_residents_of_verified_fire(
    db: Database, area_id: UUID, push: PushService | None = None
) -> int:
    """Alert every resident but the corroborators of fire [area_id]; return how
    many were alerted."""
    area = await db.fetchrow(
        "select designation, centroid_lat, centroid_lng, created_at "
        "from public.areas where id = $1",
        area_id,
    )
    if area is None or area["centroid_lat"] is None or area["centroid_lng"] is None:
        return 0
    lat, lng = float(area["centroid_lat"]), float(area["centroid_lng"])
    users = await db.fetch(
        """
        select u.id as user_id, u.language
          from public.users u
         where u.role::text = 'general_user'
           and (to_jsonb(u) ->> 'deletion_requested_at') is null
           and exists (
               select 1 from public.device_tokens dt
                where dt.user_id = u.id and dt.is_active
           )
           and u.id not in (
               select r.reporter_id from public.area_reports ar
                 join public.reports r on r.id = ar.report_id
                where ar.area_id = $1 and r.reporter_id is not null
           )
           -- Within 100 m with a fresh location: asked to corroborate instead.
           and not (
               u.location is not null
               and u.location_updated_at > now() - make_interval(mins => $4::int)
               and extensions.ST_DWithin(
                   u.location, extensions.ST_GeographyFromText($2), $3::double precision)
           )
        """,
        area_id,
        f"SRID=4326;POINT({lng} {lat})",
        CORROBORATION_RADIUS_M,
        get_settings().neighborhood_location_max_age_minutes,
    )
    if not users:
        return 0
    push = push or PushService()
    # The fire's name, "Near F. Victor Street" (v1.12.42); it was its Area
    # number, so the alert said "a fire on Area 3".
    designation = area["designation"]
    reported = area["created_at"]
    data = {
        "type": "fire_verified",
        "area_id": str(area_id),
        "designation": designation or "",
        "lat": str(lat),
        "lng": str(lng),
        "reported_at": reported.isoformat() if reported is not None else "",
    }
    languages = {u["user_id"]: language_of(u["language"]) for u in users}
    for language, ids in by_language(languages).items():
        title, body = fire_verified(language, designation)
        rows = await db.fetch(
            "select fcm_token, app_version from public.device_tokens "
            "where user_id = any($1::uuid[]) and is_active",
            ids,
        )
        # v1.12.42: a far fire has its own voice, in the reader's language, on
        # app v1.12.53's channels; an older app has neither and hears the
        # citizen recording, as before. The 100 m alert keeps the citizen one.
        voiced = [r for r in rows if has_far_voice(r["app_version"])]
        others = [r for r in rows if not has_far_voice(r["app_version"])]
        for group, sound in ((voiced, far_voice(language)), (others, "citizen")):
            for start in range(0, len(group), _BATCH):
                batch = group[start : start + _BATCH]
                result = await push.send_to_tokens(
                    tokens=[r["fcm_token"] for r in batch],
                    title=title,
                    body=body,
                    data=data,
                    sound=sound,
                    tag=f"fire-{area_id}",
                    versions=token_versions(batch),
                )
                if result.invalid_tokens:
                    await db.execute(
                        "update public.device_tokens set is_active = false "
                        "where fcm_token = any($1::text[])",
                        result.invalid_tokens,
                    )
        await record_inbox(db, ids, "fire_verified", title, body, data)
    log.info("fire_verified_broadcast", area_id=str(area_id), users=len(users))
    return len(users)
