"""Coordinator reminder pings (PRD v14 §4.13.2).

A coordinator is often in a pocket, a car, or asleep when a fire comes in.
The new-fire push rings once (``incident_notify.notify_staff_new_incident``,
which starts a row here for each coordinator it reached). If they do not open
the incident, this repeats it on a fixed schedule — vibrate only at +2 min,
with their agency's sound at +5, vibrate only at +7, with the sound at +10 —
and then stops; the first push stays in their inbox.

It stops early, for one coordinator, when they open the incident
(``POST /incidents/{id}/seen``), when anyone of their agency acknowledges it,
or when it leaves the live feed. Each reminder replaces the earlier push in
the shade (same tag), so the phone shows one notification, not five.

The tick runs every 20 s. A free-tier host that sleeps skips ticks while
asleep; a new report wakes it, so the cycle normally runs whole.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.db.session import Database, database
from app.integrations.fcm import PushService, sound_for_agency
from app.services.incident import active_area_sql

log = get_logger(__name__)

# (seconds after the first push, whether it plays the sound). A step without
# sound only vibrates.
SCHEDULE: tuple[tuple[int, bool], ...] = ((120, False), (300, True), (420, False), (600, True))

_TICK_SECONDS = 20
_scheduler: AsyncIOScheduler | None = None


async def start_pings(db: Database, area_id: UUID, user_ids: list[UUID]) -> None:
    """Begin the reminder cycle for these coordinators (once per Area each)."""
    await db.execute(
        """
        insert into public.coordinator_pings (area_id, user_id)
        select $1, uid from unnest($2::uuid[]) as uid
        on conflict (area_id, user_id) do nothing
        """,
        area_id,
        user_ids,
    )


async def stop_pings(db: Database, area_id: UUID, user_id: UUID, reason: str) -> bool:
    """End one coordinator's reminders for an Area; True if any were still due."""
    row = await db.fetchrow(
        """
        update public.coordinator_pings
           set stopped_at = now(), stop_reason = $3
         where area_id = $1 and user_id = $2 and stopped_at is null
        returning area_id
        """,
        area_id,
        user_id,
        reason,
    )
    return row is not None


async def _send_reminder(
    db: Database, push: PushService, row: Mapping[str, Any], *, sound: bool
) -> None:
    """Push one reminder to the coordinator's phones; retire dead tokens."""
    tokens = [
        t["fcm_token"]
        for t in await db.fetch(
            "select fcm_token from public.device_tokens where user_id = $1 and is_active",
            row["user_id"],
        )
    ]
    if not tokens:
        return
    area_id = str(row["area_id"])
    result = await push.send_to_tokens(
        tokens=tokens,
        title=f"Fire reported: {row['designation'] or 'new incident'}",
        body="Still waiting for you. Tap to open it and acknowledge.",
        data={"type": "incident_reminder", "area_id": area_id, "event": "incident_reminder"},
        sound=sound_for_agency(row["agency_type"]) if sound else None,
        silent=not sound,
        tag=f"incident-{area_id}",
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )


async def run_pings(db: Database, push: PushService) -> int:
    """One pass: stop the cycles that are over, send the reminders now due.

    Returns the number of reminders sent. Each step is claimed with a
    conditional update before it is sent, so two servers never send it twice.
    """
    rows = await db.fetch(
        f"""
        select p.area_id, p.user_id, p.step, a.designation,
               u.agency_type::text as agency_type,
               extract(epoch from now() - p.started_at) as age,
               ({active_area_sql("a")}) and u.is_active as live,
               exists (
                   select 1 from public.area_acceptances aa
                   where aa.area_id = p.area_id and aa.agency = u.agency_type
               ) as acknowledged
        from public.coordinator_pings p
        join public.areas a on a.id = p.area_id
        join public.users u on u.id = p.user_id
        where p.stopped_at is null
        """
    )
    sent = 0
    for row in rows:
        if not row["live"]:
            await stop_pings(db, row["area_id"], row["user_id"], "closed")
            continue
        if row["acknowledged"]:
            await stop_pings(db, row["area_id"], row["user_id"], "acknowledged")
            continue
        step = int(row["step"])
        if step >= len(SCHEDULE):
            await stop_pings(db, row["area_id"], row["user_id"], "done")
            continue
        offset, sound = SCHEDULE[step]
        if float(row["age"]) < offset:
            continue
        last = step + 1 == len(SCHEDULE)
        claimed = await db.fetchrow(
            """
            update public.coordinator_pings
               set step = step + 1,
                   stopped_at = case when $4 then now() end,
                   stop_reason = case when $4 then 'done' end
             where area_id = $1 and user_id = $2 and step = $3 and stopped_at is null
            returning step
            """,
            row["area_id"],
            row["user_id"],
            step,
            last,
        )
        if claimed is None:
            continue
        try:
            await _send_reminder(db, push, row, sound=sound)
            sent += 1
        except Exception:
            log.error(
                "coordinator_ping_failed",
                area_id=str(row["area_id"]),
                user_id=str(row["user_id"]),
                exc_info=True,
            )
    return sent


async def coordinator_pings_tick() -> None:
    """Scheduled job: run one pass against the shared database."""
    if not database.is_connected:
        return
    try:
        sent = await run_pings(database, PushService())
    except Exception:
        log.error("coordinator_pings_tick_failed", exc_info=True)
        return
    if sent:
        log.info("coordinator_pings_sent", count=sent)


def start_coordinator_pings_scheduler() -> None:
    """Start the reminder scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        coordinator_pings_tick,
        trigger="interval",
        seconds=_TICK_SECONDS,
        id="coordinator_pings",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("coordinator_pings_scheduler_started")


def shutdown_coordinator_pings_scheduler() -> None:
    """Stop the scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("coordinator_pings_scheduler_stopped")
