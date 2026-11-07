"""A staff member's personal email (6 Nov 2026): the links it gets, and adding one.

Coordinators and responders made from now on sign in with an @replit.com
address, which has no mailbox, so their password links go to their own email
(``users.personal_email``; app/services/staff_links.py).

GET /auth/staff/password-link   the emailed link: confirms the personal email,
                                then opens the set-password page through a
                                fresh Supabase recovery link.
GET /auth/personal-email/verify the emailed link: confirms the personal email.
PUT /auth/me/personal-email     a coordinator or responder sets theirs from
                                Profile; a link to confirm it goes there.

Forgot password? for such an account (routes/password_reset.py) sends its link
to the personal email through :func:`send_staff_resets`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.deps import AuthClientDep, DatabaseDep, EmailClientDep, SessionUser
from app.api.routes.password_reset import reset_page_url
from app.core.exceptions import AppError, BadRequestError, ForbiddenError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.brevo_email import BrevoEmailClient
from app.schemas.auth import PersonalEmailRequest
from app.schemas.common import MessageResponse
from app.services.disposable_email import ensure_not_disposable
from app.services.link_page import link_page
from app.services.responder_accounts import is_staff_address
from app.services.staff_links import (
    RESET_FOR,
    LinkError,
    password_link,
    read_token,
    reset_email,
    verify_email,
    verify_link,
)

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

STAFF_ROLES = ("sub_admin", "response_team")


# --------------------------------------------------------------------------- #
# The small pages a link lands on
# --------------------------------------------------------------------------- #
def _expired() -> HTMLResponse:
    return link_page(
        "Link expired",
        "This link has expired",
        "Open the RepLiT app, tap Forgot password?, and enter your sign-in address "
        "or your personal email. We will email you a new link.",
        status_code=400,
    )


async def _staff_row(db: Database, user_id: UUID) -> dict[str, object] | None:
    row = await db.fetchrow(
        "select email, personal_email, is_active from public.users where id = $1",
        user_id,
    )
    return dict(row) if row is not None else None


def _matches(row: dict[str, object] | None, sent_to: str) -> bool:
    """The account is live and still has the address the link went to."""
    return (
        row is not None
        and bool(row["is_active"])
        and str(row["personal_email"] or "").strip().lower() == sent_to
    )


# --------------------------------------------------------------------------- #
# The links
# --------------------------------------------------------------------------- #
@router.get("/staff/password-link", include_in_schema=False)
async def staff_password_link(
    db: DatabaseDep,
    auth: AuthClientDep,
    token: str = Query(min_length=10, max_length=2048),
) -> Response:
    """Confirm the personal email, then go to the set-password page."""
    try:
        user_id, sent_to = read_token(token, "password")
    except LinkError:
        return _expired()
    row = await _staff_row(db, user_id)
    if not _matches(row, sent_to):
        return _expired()
    assert row is not None
    await db.execute(
        "update public.users set personal_email_verified_at = "
        "coalesce(personal_email_verified_at, now()) where id = $1",
        user_id,
    )
    try:
        resp = await auth.admin_generate_link(
            link_type="recovery", email=str(row["email"]), redirect_to=reset_page_url()
        )
    except AppError:
        log.warning("staff_password_link_failed", user_id=str(user_id), exc_info=True)
        resp = {}
    link = resp.get("action_link") or (resp.get("properties") or {}).get("action_link")
    if not isinstance(link, str) or not link:
        return link_page(
            "Try again",
            "Something went wrong",
            "Your email is confirmed, but the password page did not open. Open this "
            "link again in a minute.",
            status_code=502,
        )
    log.info("staff_password_link_opened", user_id=str(user_id))
    return RedirectResponse(link, status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/personal-email/verify", include_in_schema=False)
async def verify_personal_email(
    db: DatabaseDep,
    token: str = Query(min_length=10, max_length=2048),
) -> HTMLResponse:
    """Confirm a personal email added from Profile."""
    try:
        user_id, sent_to = read_token(token, "verify")
    except LinkError:
        return link_page(
            "Link expired",
            "This link has expired",
            "Open Profile in the RepLiT app and add your personal email again. We "
            "will send a new link.",
            status_code=400,
        )
    row = await _staff_row(db, user_id)
    if not _matches(row, sent_to):
        return link_page(
            "Link expired",
            "This link is out of date",
            "Your account has a different personal email now. Use the link in the "
            "newest email we sent.",
            status_code=400,
        )
    await db.execute(
        "update public.users set personal_email_verified_at = now() where id = $1",
        user_id,
    )
    log.info("personal_email_verified", user_id=str(user_id))
    return link_page(
        "Email confirmed",
        "Your email is confirmed",
        "If you forget your RepLiT password, we will send the reset link to this "
        "address. You can close this page.",
    )


# --------------------------------------------------------------------------- #
# Adding one from Profile
# --------------------------------------------------------------------------- #
_VERIFY_COOLDOWN = timedelta(seconds=60)
_last_verify: dict[UUID, datetime] = {}


async def _send_verify(
    email_client: BrevoEmailClient, user_id: UUID, to: str, address: str
) -> None:
    try:
        message = verify_email(address=address, link=verify_link(user_id, to))
        await email_client.send(
            to=to,
            subject="Confirm your personal email for RepLiT",
            html=message.html,
            text=message.text,
        )
    except AppError:
        log.warning("personal_email_verify_send_failed", user_id=str(user_id))


@router.put(
    "/me/personal-email",
    response_model=MessageResponse,
    summary="Set my personal email (coordinator or responder)",
)
async def set_personal_email(
    payload: PersonalEmailRequest,
    user: SessionUser,
    db: DatabaseDep,
    email_client: EmailClientDep,
    background: BackgroundTasks,
) -> MessageResponse:
    """Where this staff account's password links go; a link to confirm it is sent."""
    if user.role not in STAFF_ROLES:
        raise ForbiddenError("Only coordinators and responders have a personal email.")
    email = str(payload.email).strip().lower()
    if is_staff_address(email):
        raise BadRequestError(
            "Use an email you can open: @replit.com addresses have no mailbox.",
            error_code="not_personal",
        )
    ensure_not_disposable(email)
    row = await db.fetchrow(
        "select personal_email, personal_email_verified_at from public.users where id = $1",
        user.id,
    )
    same = row is not None and str(row["personal_email"] or "").lower() == email
    if same and row is not None and row["personal_email_verified_at"] is not None:
        return MessageResponse(message="That email is already confirmed.")
    if not same:
        await db.execute(
            "update public.users set personal_email = $2, "
            "personal_email_verified_at = null, updated_at = now() where id = $1",
            user.id,
            email,
        )
    now = datetime.now(UTC)
    last = _last_verify.get(user.id)
    if last is None or now - last >= _VERIFY_COOLDOWN or not same:
        _last_verify[user.id] = now
        background.add_task(_send_verify, email_client, user.id, email, user.email or "")
    log.info("personal_email_set", user_id=str(user.id))
    return MessageResponse(message=f"We sent a link to {email}. Open it to confirm.")


# --------------------------------------------------------------------------- #
# Forgot password?
# --------------------------------------------------------------------------- #
async def send_staff_resets(
    db: Database, email_client: BrevoEmailClient, email: str
) -> bool:
    """Reset links for the staff accounts ``email`` names — as their sign-in or as
    their personal email — each sent to its personal email. False when it names
    none, so the caller sends the usual reset instead."""
    rows = await db.fetch(
        """
        select id, email, personal_email from public.users
         where personal_email is not null and is_active
           and lower(email) like '%@replit.com'
           and (lower(email) = $1 or lower(personal_email) = $1)
         limit 3
        """,
        email.strip().lower(),
    )
    if not rows:
        return False
    for row in rows:
        to = str(row["personal_email"])
        message = reset_email(
            address=str(row["email"]), link=password_link(row["id"], to, RESET_FOR)
        )
        await email_client.send(
            to=to,
            subject="Reset your RepLiT password",
            html=message.html,
            text=message.text,
        )
    log.info("staff_reset_email_sent", accounts=len(rows))
    return True
