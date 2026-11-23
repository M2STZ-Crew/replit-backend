"""A staff account's life: made, welcomed, turned off and on.

Responders and, since v1.12.51, Coordinators (23 Nov 2026: "make the account
management in coordinator and responder the same"). Shared by a coordinator's
team routes (app/api/routes/team.py), the Admins' (app/services/staff_admin.py)
and an accepted affiliate's first Coordinator (app/api/routes/affiliates.py),
so an account is made and turned off the same way whoever does it. Who may is
each route's check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request

from app.core.exceptions import AppError, BadRequestError, ConflictError, ExternalServiceError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.supabase_auth import AuthError, SupabaseAuthClient
from app.schemas.auth import AuthenticatedUser
from app.services.audit import record_audit
from app.services.disposable_email import ensure_not_disposable
from app.services.names import one_line
from app.services.responder_accounts import (
    InvalidNameError,
    StaffRole,
    is_staff_address,
    staff_email,
    staff_like_pattern,
)
from app.services.staff_links import WELCOME_FOR, password_link, welcome_email

log = get_logger(__name__)

# Long enough to mean "until reactivated" (Supabase Auth takes a duration).
_BAN_FOREVER = "876000h"


@dataclass(frozen=True)
class StaffKind:
    """Which staff account: a Responder or a Coordinator."""

    role: str  # users.role; our own constant, so it may go into SQL
    key: StaffRole  # in addresses, audit actions and their metadata
    word: str  # its title
    noun: str  # in a sentence


RESPONDER = StaffKind("response_team", "responder", "Responder", "responder")
COORDINATOR = StaffKind("sub_admin", "coordinator", "Coordinator", "Coordinator")


async def next_address(
    db: Database, first: str, last: str, agency: str, kind: StaffKind = RESPONDER
) -> str:
    """The sign-in address an account of this name would get now."""
    try:
        rows = await db.fetch(
            "select email from public.users where lower(email) like $1",
            staff_like_pattern(first, last, agency, kind.key),
        )
        taken = [str(r["email"]) for r in rows if r["email"]]
        return staff_email(first, last, agency, kind.key, taken)
    except InvalidNameError as exc:
        raise BadRequestError(str(exc)) from exc


def own_email(raw: str | None, kind: StaffKind = RESPONDER) -> str | None:
    """A staff member's own email as stored, or a 400: one they can open."""
    personal = str(raw).strip().lower() if raw else None
    if personal and is_staff_address(personal):
        raise BadRequestError(
            f"Use the {kind.noun}'s own email: @replit.com addresses have no mailbox.",
            error_code="not_personal",
        )
    ensure_not_disposable(personal, field="personal_email")
    return personal


async def make_sign_in(
    db: Database,
    auth: SupabaseAuthClient,
    *,
    first: str,
    last: str,
    agency: str,
    password: str,
    kind: StaffKind = RESPONDER,
) -> tuple[UUID, str]:
    """A new sign-in at the next free address: its id and the address.

    Always a new account, never one that exists. If two people make the same
    name at once, the second takes the next number rather than failing.
    """
    created: dict[str, Any] | None = None
    email = ""
    for attempt in range(3):
        email = await next_address(db, first, last, agency, kind)
        try:
            created = await auth.admin_create_user(
                email=email,
                password=password,
                email_confirm=True,
                user_metadata={"full_name": f"{first} {last}"},
            )
            break
        except (BadRequestError, AuthError) as exc:
            # Taken between the check and the create: take the next number.
            if "already" in exc.message.lower() and attempt < 2:
                log.info("staff_email_race", email=email)
                continue
            if isinstance(exc, AuthError):
                # Supabase's refusal, not the caller's sign-in: never their 401.
                raise ConflictError(
                    "The account could not be made. Try again in a moment."
                ) from exc
            raise
    assert created is not None
    raw_id = created.get("id") or (created.get("user") or {}).get("id")
    if not isinstance(raw_id, str):
        raise ExternalServiceError("Account created but no id was returned by Supabase Auth.")
    return UUID(raw_id), email


async def discard_sign_in(auth: SupabaseAuthClient, user_id: UUID) -> None:
    """Never leave a sign-in without its profile behind."""
    try:
        await auth.admin_delete_user(user_id=str(user_id))
    except Exception:
        log.error("staff_rollback_failed", user_id=str(user_id), exc_info=True)


async def write_profile(
    conn: Any,
    kind: StaffKind,
    user_id: UUID,
    *,
    agency: str,
    org_id: UUID,
    full_name: str,
    mobile: str | None,
    created_by: UUID,
    personal: str,
) -> None:
    """Make a new sign-in's profile this kind of account."""
    updated = await conn.execute(
        f"""
        update public.users
           set role = '{kind.role}',
               agency_type = $2::public.agency_type,
               primary_org_id = $3,
               full_name = $4,
               mobile = $5,
               created_by = $6,
               personal_email = $7,
               personal_email_verified_at = null,
               is_active = true,
               updated_at = now()
         where id = $1
        """,
        user_id,
        agency,
        org_id,
        full_name,
        mobile,
        created_by,
        personal,
    )
    if updated.endswith(" 0"):
        raise ExternalServiceError("Account created but its profile was not found.")


async def put_on_roster(
    conn: Any, kind: StaffKind, org_id: UUID, user_id: UUID, title: str | None
) -> None:
    await conn.execute(
        f"""
        insert into public.org_roster (organization_id, user_id, member_role, title)
        values ($1, $2, '{kind.role}', $3)
        on conflict (organization_id, user_id) do update
           set member_role = excluded.member_role, title = excluded.title,
               is_active = true, updated_at = now()
        """,
        org_id,
        user_id,
        title,
    )


async def send_welcome(
    email_client: BrevoEmailClient,
    *,
    user_id: UUID,
    name: str,
    organization: str,
    address: str,
    personal: str,
    made_by: str,
    kind: StaffKind = RESPONDER,
) -> tuple[bool, str | None]:
    """Email the link that sets the password: whether it went, and why not."""
    subject = (
        f"You're a Coordinator for {one_line(organization)} on RepLiT"
        if kind == COORDINATOR
        else "Your RepLiT Responder account is ready"
    )
    try:
        message = welcome_email(
            name=name,
            role=kind.word,
            organization=organization,
            address=address,
            link=password_link(user_id, personal, WELCOME_FOR),
            made_by=made_by,
        )
        await email_client.send(
            to=personal, subject=subject, html=message.html, text=message.text
        )
    except AppError as exc:
        log.warning("staff_invite_failed", kind=kind.key, user_id=str(user_id), error=str(exc))
        return False, (
            f"The account is ready, but the email to {personal} could not be sent. "
            f"They can use “Forgot password?” on the app with {address} or {personal}."
        )
    return True, None


async def turn_off(
    db: Database,
    auth: SupabaseAuthClient,
    request: Request | None,
    actor: AuthenticatedUser,
    user_id: UUID,
    *,
    name: str | None,
    kind: StaffKind = RESPONDER,
) -> list[str]:
    """Sign-in stops, pushes stop, a live response is released and the history
    stays. The incidents it was released from come back."""
    # Supabase first: if the ban fails nothing has changed, and the account is
    # not left marked inactive while it can still make sessions.
    await auth.admin_update_user(user_id=str(user_id), attributes={"ban_duration": _BAN_FOREVER})
    async with db.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            """
            update public.dispatch_logs
               set status = 'withdrawn', withdrawn_at = now()
             where responder_id = $1 and status = 'active'
             returning area_id
            """,
            user_id,
        )
        released = [str(r["area_id"]) for r in rows]
        await conn.execute(
            "update public.device_tokens set is_active = false where user_id = $1", user_id
        )
        await conn.execute(
            """
            update public.users
               set is_active = false, deactivated_at = now(), deactivated_by = $2,
                   updated_at = now()
             where id = $1
            """,
            user_id,
            actor.id,
        )
        await record_audit(
            conn,
            request,
            actor,
            action=f"user.{kind.key}_deactivated",
            entity_type="user",
            entity_id=user_id,
            metadata={"responses_released": released, kind.key: name},
        )
    return released


async def turn_on(
    db: Database,
    auth: SupabaseAuthClient,
    request: Request | None,
    actor: AuthenticatedUser,
    user_id: UUID,
    *,
    name: str | None,
    kind: StaffKind = RESPONDER,
) -> None:
    """Lift the ban. Their old password works again."""
    await auth.admin_update_user(user_id=str(user_id), attributes={"ban_duration": "none"})
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            update public.users
               set is_active = true, deactivated_at = null, deactivated_by = null,
                   updated_at = now()
             where id = $1
            """,
            user_id,
        )
        await record_audit(
            conn,
            request,
            actor,
            action=f"user.{kind.key}_reactivated",
            entity_type="user",
            entity_id=user_id,
            metadata={kind.key: name},
        )
