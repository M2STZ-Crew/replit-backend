"""A resident's account deletion: frozen for 30 days, then gone (v1.12.35).

16 Nov 2026: "make the account is in freeze for 30 days before actual deleting
it? (they can still recover it within 30 days)".

Asking (the app's Profile, or reportwhatslit-app.vercel.app/delete-account)
freezes the account at once: every session is signed out, its phones stop
getting alerts, and every sign-in and request is refused with 403
``account_pending_deletion`` and the day it goes. Within the 30 days, Restore
(POST /auth/restore, offered by the app at sign-in and by the residents' site)
brings everything back as it was. After them, :func:`purge_due` deletes it for
good: any National ID photos still held, then the sign-in, and with it (on
delete cascade) the profile, phones, inbox and verification records. The
reports they sent stay, without them (reports.reporter_id becomes null), as
part of the incident record.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, ForbiddenError
from app.core.logging import get_logger
from app.integrations.supabase_auth import AuthError
from app.schemas.auth import AuthenticatedUser
from app.services.audit import record_audit
from app.services.national_id import photo_paths, remove_photos

log = get_logger(__name__)

MANILA = ZoneInfo("Asia/Manila")

# Where a resident restores or deletes an account without the app.
RESIDENT_SITE = "reportwhatslit-app.vercel.app"

# Accounts deleted per run of the hourly job: a backlog drains over a few hours
# rather than holding the job for minutes.
PURGE_BATCH = 25


def grace_days() -> int:
    return get_settings().account_deletion_grace_days


def delete_after(requested_at: datetime) -> datetime:
    """When an account asked to be deleted at ``requested_at`` goes for good."""
    return requested_at + timedelta(days=grace_days())


def day_of(when: datetime) -> str:
    """ "16 December 2026", in Philippine time."""
    local = when.astimezone(MANILA)
    return f"{local.day} {local:%B %Y}"


def pending_error(requested_at: datetime) -> ForbiddenError:
    """The refusal a frozen account gets, at sign-in and on every request."""
    when = delete_after(requested_at)
    return ForbiddenError(
        f"This account is set to be deleted on {day_of(when)}. To keep it, choose "
        f"Restore my account when you sign in, or go to {RESIDENT_SITE}/delete-account.",
        error_code="account_pending_deletion",
        details={"delete_after": when.isoformat()},
    )


async def schedule(db: Any, user_id: UUID) -> datetime:
    """Freeze the account and return when it goes. Asking twice keeps the first date."""
    requested = await _guarded(
        db.fetchval(
            """
        update public.users
           set deletion_requested_at = coalesce(deletion_requested_at, now())
         where id = $1
        returning deletion_requested_at
        """,
            user_id,
        )
    )
    # No alerts while frozen; a restored account's phone registers again at
    # its next sign-in.
    await db.execute(
        "update public.device_tokens set is_active = false where user_id = $1", user_id
    )
    return delete_after(requested)


async def restore(db: Any, user_id: UUID) -> bool:
    """Unfreeze the account; False when it was not frozen."""
    found = await _guarded(
        db.fetchval(
            """
            update public.users set deletion_requested_at = null
             where id = $1 and deletion_requested_at is not null
            returning id
            """,
            user_id,
        )
    )
    return found is not None


async def purge_due(db: Any, auth: Any, storage: Any) -> int:
    """Delete for good the accounts frozen for the whole grace period.

    Returns how many went. One that cannot go now (its photos or its sign-in
    could not be removed) is left frozen and tried again on the next run.
    """
    days = grace_days()
    due = await db.fetch(
        """
        select id from public.users
         where deletion_requested_at is not null
           and deletion_requested_at <= now() - make_interval(days => $1::int)
           and role::text = 'general_user'
         order by deletion_requested_at
         limit $2
        """,
        days,
        PURGE_BATCH,
    )
    deleted = 0
    for row in due:
        user_id: UUID = row["id"]
        try:
            await remove_photos(storage, photo_paths(user_id).values())
        except Exception:
            log.error("account_purge_photos_failed", user_id=str(user_id), exc_info=True)
            continue
        # Before the account goes: after, its id names no one (the line keeps
        # a null actor).
        await record_audit(
            db,
            None,
            AuthenticatedUser(id=user_id, role="general_user"),
            action="account.deleted",
            entity_type="user",
            entity_id=user_id,
            metadata={"via": "grace_period_ended", "days": days},
        )
        try:
            await auth.admin_delete_user(user_id=str(user_id))
        except AuthError:
            log.error("account_purge_failed", user_id=str(user_id))
            continue
        deleted += 1
        log.info("account_purged", user_id=str(user_id))
    return deleted


async def purge_unconfirmed(db: Any, auth: Any, storage: Any) -> int:
    """Delete the residents who never confirmed their email (v1.12.38).

    18 Nov 2026: an address nobody owns could keep a working account, because
    "Later" skipped the emailed link. Now nothing works until it is opened, and
    an account made from ``unconfirmed_purge_since`` on that is still
    unconfirmed ``unconfirmed_account_hours`` after sign-up is deleted. Older
    accounts signed up when Later was allowed, and are kept. Returns how many
    went; one that cannot go now is tried again on the next run.
    """
    settings = get_settings()
    hours = settings.unconfirmed_account_hours
    due = await db.fetch(
        """
        select u.id from public.users u
         where u.role::text = 'general_user'
           and u.created_at >= $1
           and u.created_at <= now() - make_interval(hours => $2::int)
           and not exists (
               select 1 from public.user_verifications v
                where v.user_id = u.id
                  and v.type::text = 'email'
                  and v.status::text = 'verified'
           )
         order by u.created_at
         limit $3
        """,
        datetime.fromisoformat(settings.unconfirmed_purge_since),
        hours,
        PURGE_BATCH,
    )
    deleted = 0
    for row in due:
        user_id: UUID = row["id"]
        try:
            await remove_photos(storage, photo_paths(user_id).values())
        except Exception:
            log.error("unconfirmed_purge_photos_failed", user_id=str(user_id), exc_info=True)
            continue
        await record_audit(
            db,
            None,
            AuthenticatedUser(id=user_id, role="general_user"),
            action="account.deleted",
            entity_type="user",
            entity_id=user_id,
            metadata={"via": "email_never_confirmed", "hours": hours},
        )
        try:
            await auth.admin_delete_user(user_id=str(user_id))
        except AuthError:
            log.error("unconfirmed_purge_failed", user_id=str(user_id))
            continue
        deleted += 1
        log.info("unconfirmed_account_purged", user_id=str(user_id))
    return deleted


async def _guarded(query: Any) -> Any:
    """Run a query on deletion_requested_at; a database still without the column
    (migration 20261116090000 not applied) is a 503, said plainly, not a 500."""
    try:
        return await query
    except Exception as exc:
        if "deletion_requested_at" in str(exc):
            log.error("account_deletion_column_missing")
            raise ExternalServiceError(
                "Deleting or restoring an account is not available just now. Try again later.",
                status_code=503,
                error_code="deletion_unavailable",
            ) from exc
        raise
