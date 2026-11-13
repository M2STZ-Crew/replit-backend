"""Tell phones a new version of the app is out (backend v1.12.29, v1.12.30).

12 November 2026: "create an "New Update!" notification, the sound to be
follow. still vibrates". The app's releases are published on GitHub, with a
``latest.json`` beside the APK: what the app's own "Check for updates" reads.
Every ``APP_UPDATE_CHECK_MINUTES`` (2; 10 before v1.12.32) this reads it too,
and when the release workflow asks (v1.12.32, below), and everyone on an
Android phone that is on an older version hears of it once per version: a
push, "New Update!", on a channel of its own, vibrating, and a row in their
inbox. Tapping it opens Check for updates.

The push plays the update's own recording in the reader's language (v1.12.30:
English or Tagalog, on that language's channel) on a phone with app v1.12.38
or later, which has the recordings; an older phone hears its own tone, on
"App updates" (``APP_UPDATES_CHANNEL``).

Android only: an iPhone installs a new version by hand, from the IPA, and its
own Check for updates says when there is one.

A phone's version is the one it last registered with
(``device_tokens.app_version``): "1.12.37", or "1.12.36 (58)" from an app
before 1.12.37, which wrote the build number too. A phone that never said is
told. The inbox row is what marks someone told, so it is written before the
push goes: a push that fails half way is not sent twice.

It runs only where the service has a public address (Render), like the keep
awake knock: never from a laptop or the tests.

v1.12.32 (13 November 2026: "the "new update" push notification doesn't work
on my android phone"): it went, but only at the next check, 10 minutes apart.
App 1.12.40 came out at 12:16:56; by 12:18 the phone had installed it from the
update banner, and the 12:26 check found it up to date. Now the app's release
workflow asks for a check as soon as it has published (POST
/app-updates/check, :func:`check_now`), so the push goes within seconds, and
the scheduled check runs every 2 minutes for when that ask does not arrive.
Checks run one at a time, so the two cannot tell anyone twice, and nobody told
of a version is told of an older one afterwards.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.fcm import (
    APP_UPDATE_RECORDINGS,
    APP_UPDATE_RECORDINGS_SINCE,
    APP_UPDATES_CHANNEL,
    PushService,
)
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

# An asked-for check (the release workflow's) this soon after the last one is
# answered with what that one found: the ask is public, and a burst of asks
# must not become a burst of reads from GitHub. Scheduled checks always read.
ASK_COOLDOWN_SECONDS = 10.0

# The clock asks are timed by (the tests set their own).
_clock = time.monotonic


@dataclass(frozen=True)
class Checked:
    """What a check found: the newest release (None when it could not be
    read) and how many people it told of it just then.
    """

    version: str | None
    told: int


# One check at a time: two at once could both find the same people not yet
# told, and tell them twice. Made on first use, in the running event loop.
_lock: asyncio.Lock | None = None
_last: Checked | None = None
_last_asked_at: float | None = None


def _check_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


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


def _version_of(installed: str | None) -> tuple[int, ...] | None:
    """The version a phone registered with: "1.12.36 (58)" reads as 1.12.36."""
    core = (installed or "").strip().split(" ")[0]
    if not _VERSION.match(core):
        return None
    return tuple(map(int, core.split(".")))


def is_older(installed: str | None, latest: str) -> bool:
    """Whether a phone that registered as ``installed`` is before ``latest``.

    "1.12.36 (58)" reads as 1.12.36. A phone that never said counts as older.
    """
    version = _version_of(installed)
    return version is None or version < tuple(map(int, latest.split(".")))


def has_recordings(installed: str | None) -> bool:
    """Whether a phone on ``installed`` has the update's recordings and their
    channels (app v1.12.38). A phone that never said has not.
    """
    version = _version_of(installed)
    return version is not None and version >= APP_UPDATE_RECORDINGS_SINCE


def update_channel(language: Language, recordings: bool) -> tuple[str, str | None]:
    """The channel a phone is told on, and the recording it plays (None: the
    phone's own tone).
    """
    if not recordings:
        return APP_UPDATES_CHANNEL, None
    channel, recording = APP_UPDATE_RECORDINGS.get(language, APP_UPDATE_RECORDINGS["en"])
    return channel, recording


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


# Every active Android phone of someone not yet told of $1 or of a newer
# version (v1.12.32): a check that reads the release a moment late, while the
# one before it read the next, tells nobody of the older one. Versions compare
# as numbers ({1,12,9} < {1,12,10}); an inbox row whose version is not one is
# ignored rather than failing the check.
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
            and case when n.data ->> 'version' ~ '^[0-9]+[.][0-9]+[.][0-9]+$'
                     then string_to_array(n.data ->> 'version', '.')::int[]
                end >= string_to_array($1, '.')::int[]
       )
"""


async def announce(db: Database, push: PushService, version: str) -> int:
    """Tell everyone on an older version that ``version`` is out.

    Returns how many people were told (each once, whatever their phones).
    """
    # Each person once, in their language; each of their phones with the
    # sound it can play.
    due: dict[UUID, tuple[Language, list[tuple[str, bool]]]] = {}
    for row in await db.fetch(_DUE_SQL, version):
        if not is_older(row["app_version"], version):
            continue
        _, phones = due.setdefault(row["user_id"], (language_of(row["language"]), []))
        phones.append((row["fcm_token"], has_recordings(row["app_version"])))
    if not due:
        return 0

    groups: dict[Language, tuple[list[UUID], dict[bool, list[str]]]] = {}
    for user_id, (language, phones) in due.items():
        users, by_sound = groups.setdefault(language, ([], {}))
        users.append(user_id)
        for token, recordings in phones:
            by_sound.setdefault(recordings, []).append(token)

    for language, (users, by_sound) in groups.items():
        title, body = update_copy(language, version)
        await record_inbox(db, users, INBOX_TYPE, title, body, {"version": version})
        for recordings, tokens in by_sound.items():
            channel, recording = update_channel(language, recordings)
            for start in range(0, len(tokens), _MULTICAST_LIMIT):
                result = await push.send_to_tokens(
                    tokens=tokens[start : start + _MULTICAST_LIMIT],
                    title=title,
                    body=body,
                    data={"type": INBOX_TYPE, "version": version},
                    channel=channel,
                    recording=recording,
                    # A newer version's push replaces an older one in the shade.
                    tag=INBOX_TYPE,
                )
                # How each send went, so "it did not arrive" has an answer in
                # the logs (v1.12.32).
                log.info(
                    "app_update_sent",
                    version=version,
                    channel=channel,
                    sent=result.success_count,
                    failed=result.failure_count,
                )
                if result.invalid_tokens:
                    await db.execute(
                        "update public.device_tokens set is_active = false "
                        "where fcm_token = any($1::text[])",
                        result.invalid_tokens,
                    )
    log.info("app_update_announced", version=version, people=len(due))
    return len(due)


async def check_now(
    db: Database,
    push: PushService,
    client: httpx.AsyncClient,
    *,
    asked: bool = False,
) -> Checked:
    """Read the newest release and tell whoever is behind it, now.

    The scheduled check and the release workflow's ask (``asked``) both come
    here, one at a time. An ask within ``ASK_COOLDOWN_SECONDS`` of the last
    ask is answered with the last check's result, without reading anything.
    Never raises: a release that cannot be read, or a failed announcement,
    is logged, and the next check tries again.
    """
    global _last, _last_asked_at
    async with _check_lock():
        now = _clock()
        if (
            asked
            and _last is not None
            and _last_asked_at is not None
            and now - _last_asked_at < ASK_COOLDOWN_SECONDS
        ):
            return _last
        if asked:
            _last_asked_at = now
        version = await latest_version(client)
        told = 0
        if version is not None:
            try:
                told = await announce(db, push, version)
            except Exception:
                log.error("app_update_announce_failed", version=version, exc_info=True)
        _last = Checked(version=version, told=told)
        return _last


async def app_updates_tick() -> None:
    """Scheduled job: read the newest release and tell whoever is behind it."""
    if not database.is_connected:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        await check_now(database, PushService(), client)


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
