"""A responder account's life: made, welcomed, turned off and on.

Shared by a coordinator's team routes (app/api/routes/team.py) and the Admins'
(app/api/routes/admin_responders.py, v1.12.49), so an account is made and
turned off the same way whoever does it. Who may is each route's check.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request

from app.core.exceptions import AppError, BadRequestError, ExternalServiceError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.supabase_auth import SupabaseAuthClient
from app.schemas.auth import AuthenticatedUser
from app.services.audit import record_audit
from app.services.disposable_email import ensure_not_disposable
from app.services.responder_accounts import (
    InvalidNameError,
    is_staff_address,
    like_pattern,
    responder_email,
)
from app.services.staff_links import WELCOME_FOR, password_link, welcome_email

log = get_logger(__name__)

# Long enough to mean "until reactivated" (Supabase Auth takes a duration).
_BAN_FOREVER = "876000h"


async def next_address(db: Database, first: str, last: str, agency: str) -> str:
    """The sign-in address a responder of this name would get now."""
    try:
        rows = await db.fetch(
            "select email from public.users where lower(email) like $1",
            like_pattern(first, last, agency),
        )
        taken = [str(r["email"]) for r in rows if r["email"]]
        return responder_email(first, last, agency, taken)
    except InvalidNameError as exc:
        raise BadRequestError(str(exc)) from exc


def own_email(raw: str | None) -> str | None:
    """A responder's own email as stored, or a 400: one they can open."""
    personal = str(raw).strip().lower() if raw else None
    if personal and is_staff_address(personal):
        raise BadRequestError(
            "Use the responder's own email: @replit.com addresses have no mailbox.",
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
) -> tuple[UUID, str]:
    """A new sign-in at the next free address: its id and the address.

    If two people name the same responder at once, the second takes the next
    number rather than failing.
    """
    created: dict[str, Any] | None = None
    email = ""
    for attempt in range(3):
        email = await next_address(db, first, last, agency)
        try:
            created = await auth.admin_create_user(
                email=email,
                password=password,
                email_confirm=True,
                user_metadata={"full_name": f"{first} {last}"},
            )
            break
        except BadRequestError as exc:
            # Taken between the check and the create: take the next number.
            if "already" not in exc.message.lower() or attempt == 2:
                raise
            log.info("responder_email_race", email=email)
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
        log.error("responder_rollback_failed", user_id=str(user_id), exc_info=True)


async def send_welcome(
    email_client: BrevoEmailClient,
    *,
    user_id: UUID,
    name: str,
    organization: str,
    address: str,
    personal: str,
    made_by: str,
) -> tuple[bool, str | None]:
    """Email the link that sets the password: whether it went, and why not."""
    try:
        message = welcome_email(
            name=name,
            role="Responder",
            organization=organization,
            address=address,
            link=password_link(user_id, personal, WELCOME_FOR),
            made_by=made_by,
        )
        await email_client.send(
            to=personal,
            subject="Your RepLiT Responder account is ready",
            html=message.html,
            text=message.text,
        )
    except AppError as exc:
        log.warning("responder_invite_failed", responder_id=str(user_id), error=str(exc))
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
            action="user.responder_deactivated",
            entity_type="user",
            entity_id=user_id,
            metadata={"responses_released": released, "responder": name},
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
            action="user.responder_reactivated",
            entity_type="user",
            entity_id=user_id,
            metadata={"responder": name},
        )
