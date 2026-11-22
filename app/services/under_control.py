"""Declaring a fire under control, and withdrawing it (v1.12.49).

22 Nov 2026, answered "Coordinators declare": Fire Volunteer and BFP
coordinators, and Admins with ``codes.press``, declare it by pressing FC-2 on
the fire, and can withdraw it. A responder's FC-2 only tells command.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Request

from app.core.exceptions import ConflictError, ForbiddenError, MigrationPendingError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.services.access import PRESS_CODES, admin_access
from app.services.alarm_status import LIVE
from app.services.audit import record_audit
from app.services.incident import assert_admin_routed, assert_incident_visible, is_coordinator

log = get_logger(__name__)

# Not again while it is in effect: the first declaration's time stands.
_DECLARE_SQL = """
update public.areas a
   set under_control_at = now(), under_control_by = $2
 where a.id = $1
   and a.status::text = any($3::text[])
   and (a.under_control_at is null or a.under_control_at < a.alarm_level_set_at)
returning a.under_control_at
"""

_WITHDRAW_SQL = """
with was as (
  select id, under_control_at from public.areas where id = $1 for update
)
update public.areas a
   set under_control_at = null, under_control_by = null
  from was
 where a.id = was.id
   and a.status::text = any($2::text[])
   and was.under_control_at >= coalesce(a.alarm_level_set_at, '-infinity'::timestamptz)
returning was.under_control_at
"""


def may_declare(user: AuthenticatedUser) -> bool:
    """Fire Volunteer and BFP coordinators, and Admins who press fire codes."""
    access = admin_access(user)
    if access is not None:
        return access.can(PRESS_CODES)
    return is_coordinator(user)


async def assert_may_declare(db: Database, area_id: UUID, user: AuthenticatedUser) -> None:
    """Before FC-2 is recorded for someone whose press declares it."""
    if not may_declare(user):
        raise ForbiddenError(
            "Fire Volunteer and BFP coordinators declare a fire under control."
        )
    status = await assert_incident_visible(db, area_id, user)
    await assert_admin_routed(db, area_id, user, "declare it under control")
    if status == "reported":
        raise ConflictError("Acknowledge the fire before declaring it under control.")


async def declare(
    conn: Any, request: Request | None, user: AuthenticatedUser, area_id: UUID
) -> datetime | None:
    """Put it in effect inside the press's transaction; when, or None if nothing changed.

    Before migration 20261122090000 the press still stands, as a code only.
    """
    try:
        async with conn.transaction():  # a savepoint: the press outlives it
            at = await conn.fetchval(_DECLARE_SQL, area_id, user.id, list(LIVE))
    except asyncpg.exceptions.UndefinedColumnError:
        log.warning("under_control_migration_pending", area_id=str(area_id))
        return None
    if at is None:
        return None
    await record_audit(
        conn,
        request,
        user,
        action="incident.under_control",
        entity_type="incident",
        entity_id=area_id,
        area_id=area_id,
        after_state={"under_control_at": at},
    )
    log.info("under_control_declared", area_id=str(area_id), by=str(user.id))
    return at


async def withdraw(
    db: Database, request: Request | None, user: AuthenticatedUser, area_id: UUID
) -> None:
    """Take it back; 409 when it is not in effect."""
    if not may_declare(user):
        raise ForbiddenError("Fire Volunteer and BFP coordinators withdraw Under control.")
    await assert_incident_visible(db, area_id, user)
    await assert_admin_routed(db, area_id, user, "withdraw Under control")
    try:
        async with db.acquire() as conn, conn.transaction():
            was = await conn.fetchval(_WITHDRAW_SQL, area_id, list(LIVE))
            if was is None:
                raise ConflictError("This fire is not under control.")
            await record_audit(
                conn,
                request,
                user,
                action="incident.under_control_withdrawn",
                entity_type="incident",
                entity_id=area_id,
                area_id=area_id,
                before_state={"under_control_at": was},
            )
    except asyncpg.exceptions.UndefinedColumnError as exc:
        raise MigrationPendingError() from exc
    log.info("under_control_withdrawn", area_id=str(area_id), by=str(user.id))
