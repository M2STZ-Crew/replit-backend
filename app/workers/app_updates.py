"""Tell phones a new version of the app is out (backend v1.12.29).

12 November 2026: "create an "New Update!" notification, the sound to be
follow. still vibrates". The app's releases are published on GitHub, with a
``latest.json`` beside the APK: what the app's own "Check for updates" reads.
Every ``APP_UPDATE_CHECK_MINUTES`` (10) this reads it too, and everyone on an
Android phone that is on an older version hears of it once per version: a
push, "New Update!", on a channel of its own ("App updates": the phone's own
tone until the update's sound is chosen, and vibration), and a row in their
inbox. Tapping it opens Check for updates.

Android only: an iPhone installs a new version by hand, from the IPA, and its
own Check for updates says when there is one.

A phone's version is the one it last registered with
(``device_tokens.app_version``): "1.12.37", or "1.12.36 (58)" from an app
before 1.12.37, which wrote the build number too. A phone that never said is
told. The inbox row is what marks someone told, so it is written before the
push goes: a push that fails half way is not sent twice.

It runs only where the service has a public address (Render), like the keep
awake knock: never from a laptop or the tests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.fcm import APP_UPDATES_CHANNEL, PushService
from app.services.citizen_copy import Language, language_of
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

# The newest Android release's manifest. A plain download, not GitHub's API,
# so the API's 60 requests an hour per address do not apply.
LATEST_RELEASE_URL = (
    "https://github.com/M2STZ-Crew/replit-android/releases/latest/download/latest.json"
)

INBOX_TYPE = "app_update"

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_HEADERS = {"User-Agent": "replit-backend app-updates"}
_MULTICAST_LIMIT = 500

_scheduler: AsyncIOScheduler | None = None


def update_copy(language: Language, version: str) -> tuple[str, str]:
    """The push's title and line, in the reader's language."""
    if language == "tl":
        return "May Bagong Update!", f"Handa na ang RepLiT {version}. I-tap para mag-update."
    return "New Update!", f"RepLiT {version} is ready. Tap to update."


def version_from(manifest: object) -> str | None:
    """The version a release's latest.json names ("1.12.37"), or None."""
    if not isinstance(manifest, Mapping):
        return None
    version = manifest.get("version")
    if isinstance(version, str) and _VERSION.match(version):
        return version
    return None


def is_older(installed: str | None, latest: str) -> bool:
    """Whether a phone that registered as ``installed`` is before ``latest``.

    "1.12.36 (58)" reads as 1.12.36. A phone that never said counts as older.
    """
    core = (installed or "").strip().split(" ")[0]
    if not _VERSION.match(core):
        return True
    return tuple(map(int, core.split("."))) < tuple(map(int, latest.split(".")))


async def latest_version(client: httpx.AsyncClient) -> str | None:
    """The newest release's version, or None when it cannot be read just now."""
    try:
        response = await client.get(LATEST_RELEASE_URL, headers=_HEADERS, follow_redirects=True)
    except httpx.HTTPError as exc:
        log.warning("app_update_check_failed", error=type(exc).__name__)
        return None
    if response.status_code != 200:
        log.warning("app_update_check_unexpected", status=response.status_code)
        return None
    try:
        return version_from(response.json())
    except ValueError:
        log.warning("app_update_check_unreadable")
        return None


# Every active Android phone of someone not yet told of $1.
_DUE_SQL = """
select d.user_id, u.language, d.fcm_token, d.app_version
  from public.device_tokens d
  join public.users u on u.id = d.user_id
 where d.is_active
   and d.platform = 'android'
   and not exists (
         select 1
           from public.notifications n
          where n.user_id = d.user_id
            and n.type = 'app_update'
            and n.data ->> 'version' = $1
       )
"""


async def announce(db: Database, push: PushService, version: str) -> int:
    """Tell everyone on an older version that ``version`` is out.

    Returns how many people were told (each once, whatever their phones).
    """
    due: dict[UUID, tuple[Language, list[str]]] = {}
    for row in await db.fetch(_DUE_SQL, version):
        if not is_older(row["app_version"], version):
            continue
        _, tokens = due.setdefault(row["user_id"], (language_of(row["language"]), []))
        tokens.append(row["fcm_token"])
    if not due:
        return 0

    groups: dict[Language, tuple[list[UUID], list[str]]] = {}
    for user_id, (language, tokens) in due.items():
        users, all_tokens = groups.setdefault(language, ([], []))
        users.append(user_id)
        all_tokens.extend(tokens)

    for language, (users, tokens) in groups.items():
        title, body = update_copy(language, version)
        await record_inbox(db, users, INBOX_TYPE, title, body, {"version": version})
        for start in range(0, len(tokens), _MULTICAST_LIMIT):
            result = await push.send_to_tokens(
                tokens=tokens[start : start + _MULTICAST_LIMIT],
                title=title,
                body=body,
                data={"type": INBOX_TYPE, "version": version},
                channel=APP_UPDATES_CHANNEL,
                # A newer version's push replaces an older one in the shade.
                tag=INBOX_TYPE,
            )
            if result.invalid_tokens:
                await db.execute(
                    "update public.device_tokens set is_active = false "
                    "where fcm_token = any($1::text[])",
                    result.invalid_tokens,
                )
    log.info("app_update_announced", version=version, people=len(due))
    return len(due)


async def app_updates_tick() -> None:
    """Scheduled job: read the newest release and tell whoever is behind it."""
    if not database.is_connected:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        version = await latest_version(client)
    if version is None:
        return
    try:
        await announce(database, PushService(), version)
    except Exception:
        log.error("app_update_announce_failed", version=version, exc_info=True)


def should_run() -> bool:
    """Only where the service has a public address (Render), or when asked."""
    return bool(os.environ.get("RENDER_EXTERNAL_URL") or get_settings().keep_awake_url)


def start_app_updates_scheduler() -> None:
    """Check every APP_UPDATE_CHECK_MINUTES, first a minute after start (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    minutes = get_settings().app_update_check_minutes
    if minutes <= 0 or not should_run():
        log.info("app_updates_off", reason="disabled" if minutes <= 0 else "no public address")
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        app_updates_tick,
        trigger="interval",
        minutes=minutes,
        next_run_time=datetime.now(UTC) + timedelta(minutes=1),
        id="app_updates",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("app_updates_started", every_minutes=minutes)


def shutdown_app_updates_scheduler() -> None:
    """Stop checking (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("app_updates_stopped")
