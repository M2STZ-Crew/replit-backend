"""Keeping the free Render instance awake (8 Nov 2026).

Render's free plan stops a web service after 15 minutes without traffic from
outside, and starts it again on the next request: about 50 seconds' wait. On
7 and 8 November it stopped starting again. Requests hung until they timed
out, neither the app nor the console could sign anyone in, and only a manual
deploy brought the service back, twice.

So the service no longer sleeps. Every ``KEEP_AWAKE_MINUTES`` (10) it asks for
its own ``/health`` through its public address, which reaches it the way a
phone's request does and counts as traffic from outside; Render's own health
checks come from inside and do not. Staying up also keeps the 60 s
neighbourhood alerts and the coordinator pings running through the night,
which paused while it slept.

The address is ``KEEP_AWAKE_URL`` when set, otherwise ``RENDER_EXTERNAL_URL``,
which Render sets for a web service. Anywhere else (a laptop, the tests) there
is neither, and nothing runs. A month awake is 720 to 744 of the workspace's
750 free instance hours, with this the only service using them.

.github/workflows/keep-awake.yml is the net under it: if the service ever stops
answering anyway, it starts a deploy through Render's deploy hook.
"""

from __future__ import annotations

import os

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

_HEADERS = {"User-Agent": "replit-backend keep-awake"}


def keep_awake_url() -> str | None:
    """This service's public /health, or None where it has no public address."""
    base = get_settings().keep_awake_url or os.environ.get("RENDER_EXTERNAL_URL", "")
    base = base.strip().rstrip("/")
    if not base:
        return None
    return base if base.endswith("/health") else f"{base}/health"


async def knock(url: str, client: httpx.AsyncClient | None = None) -> bool:
    """Ask [url] once. True for a 200; never raises."""
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as own:
                response = await own.get(url, headers=_HEADERS)
        else:
            response = await client.get(url, headers=_HEADERS)
    except httpx.HTTPError as exc:
        log.warning("keep_awake_failed", error=type(exc).__name__)
        return False
    if response.status_code != 200:
        log.warning("keep_awake_unexpected", status=response.status_code)
        return False
    return True


def start_keep_awake_scheduler() -> None:
    """Knock every KEEP_AWAKE_MINUTES while there is a public address (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    minutes = get_settings().keep_awake_minutes
    url = keep_awake_url()
    if minutes <= 0 or url is None:
        log.info("keep_awake_off", reason="disabled" if minutes <= 0 else "no public address")
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        knock,
        trigger="interval",
        minutes=minutes,
        args=[url],
        id="keep_awake",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("keep_awake_started", every_minutes=minutes, url=url)


def shutdown_keep_awake_scheduler() -> None:
    """Stop knocking (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("keep_awake_stopped")
