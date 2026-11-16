"""Hourly job: delete for good the accounts frozen 30 days ago (v1.12.35).

See app/services/account_deletion.py. The server stays awake (Supabase pings
/health every 5 minutes since 16 Nov 2026), so an account goes within the hour
its 30 days end.
"""

from __future__ import annotations

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.db.session import database
from app.integrations.supabase_auth import SupabaseAuthClient
from app.integrations.supabase_storage import SupabaseStorageClient
from app.services.account_deletion import purge_due

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def account_deletion_tick() -> None:
    """One run: delete the accounts whose 30 days are over."""
    if not database.is_connected:
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            deleted = await purge_due(
                database, SupabaseAuthClient(client), SupabaseStorageClient(client)
            )
    except Exception:
        log.error("account_deletion_tick_failed", exc_info=True)
        return
    if deleted:
        log.info("account_deletion_purged", count=deleted)


def start_account_deletion_scheduler() -> None:
    """Start the hourly scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        account_deletion_tick,
        trigger="interval",
        hours=1,
        id="account_deletion",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("account_deletion_scheduler_started")


def shutdown_account_deletion_scheduler() -> None:
    """Stop the scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("account_deletion_scheduler_stopped")
