"""The links RepLiT emails to a staff member's personal address (6 Nov 2026).

A coordinator or responder signs in with an @replit.com address
(app/services/responder_accounts.py), which has no mailbox. What a password
needs goes to their own email instead, ``users.personal_email``:

* **password**: the welcome email when the account is made (good for three
  days) and Forgot password? after that (one hour). Opening it confirms the
  personal email, then opens the set-password page with a fresh Supabase
  recovery link, so a mail scanner that opened it first has spent nothing.
* **verify**: a personal email added from Profile (three days). Opening it
  confirms the address.

Each link carries a signed token: whose account, the address it was sent to,
what it does, and until when. A link sent to an address the account no longer
has does nothing. The key is derived from the service-role key, which only
this server holds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Literal
from uuid import UUID

from app.core.config import get_settings
from app.services.email_layout import TAGLINE, EmailAction, RenderedEmail, render_email

Purpose = Literal["password", "verify"]

WELCOME_FOR = timedelta(days=3)
RESET_FOR = timedelta(hours=1)
VERIFY_FOR = timedelta(days=3)

PASSWORD_PATH = "/auth/staff/password-link"
VERIFY_PATH = "/auth/personal-email/verify"


class LinkError(ValueError):
    """A token that is not ours, not for this, or out of date."""


def _key() -> bytes:
    secret = get_settings().supabase_service_role_key or ""
    return hashlib.sha256(b"replit-staff-link:" + secret.encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(
    user_id: UUID,
    email: str,
    purpose: Purpose,
    lasts: timedelta,
    *,
    now: float | None = None,
) -> str:
    """A token for ``purpose`` on ``user_id``'s account, sent to ``email``."""
    at = time.time() if now is None else now
    body = json.dumps(
        {
            "u": str(user_id),
            "e": email.strip().lower(),
            "p": purpose,
            "x": int(at + lasts.total_seconds()),
        },
        separators=(",", ":"),
    ).encode()
    payload = _b64(body)
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str, purpose: Purpose, *, now: float | None = None) -> tuple[UUID, str]:
    """The account and address a token is for. Raises :class:`LinkError`."""
    try:
        payload, sig = token.split(".", 1)
        want = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise LinkError("Not one of ours.")
        body = json.loads(_unb64(payload))
        user_id = UUID(str(body["u"]))
        email = str(body["e"])
        if body["p"] != purpose:
            raise LinkError("Not for this.")
        if (time.time() if now is None else now) > float(body["x"]):
            raise LinkError("Out of date.")
    except LinkError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise LinkError("Not one of ours.") from exc
    return user_id, email


def _base() -> str:
    return get_settings().public_base_url.rstrip("/")


def password_link(user_id: UUID, email: str, lasts: timedelta) -> str:
    """The link that confirms ``email`` and opens the set-password page."""
    return f"{_base()}{PASSWORD_PATH}?token={make_token(user_id, email, 'password', lasts)}"


def verify_link(user_id: UUID, email: str) -> str:
    """The link that confirms ``email`` as this account's personal email."""
    return f"{_base()}{VERIFY_PATH}?token={make_token(user_id, email, 'verify', VERIFY_FOR)}"


# --------------------------------------------------------------------------- #
# The emails (render_email escapes every value)
# --------------------------------------------------------------------------- #
def welcome_email(
    *, name: str, role: str, organization: str, address: str, link: str, made_by: str
) -> RenderedEmail:
    """A new coordinator's or responder's: their sign-in, and the first password."""
    return render_email(
        preheader=f"Your RepLiT sign-in is {address}. Confirm this email and set your "
        "password.",
        heading=f"You're a {role} for {organization}",
        greeting=f"Hello {name},",
        paragraphs=[
            f"{made_by} has made you a {role} on RepLiT, {TAGLINE}.",
            f"You sign in to the RepLiT mobile app with {address}.",
            "Confirm that this email is yours and choose your password with the button "
            "below. If you ever forget your password, we will send the reset link here.",
        ],
        action=EmailAction("Confirm and set my password", link),
        facts=[
            "This link works for three days. If it has expired, open the RepLiT app, "
            f"tap Forgot password?, and enter {address} or this email address.",
        ],
        notice="If you were not expecting this email, you can ignore it. Do not forward "
        "it, because the link lets whoever opens it set the account's password.",
        reason="You are receiving this email because this address was given as your "
        "personal email for a RepLiT account.",
    )


def reset_email(*, address: str, link: str) -> RenderedEmail:
    """Forgot password? for a staff account, sent to its personal email."""
    return render_email(
        preheader=f"Choose a new password for {address}. The link works for one hour.",
        heading="Reset your password",
        paragraphs=[
            f"We received a request to reset the password for the RepLiT account "
            f"{address}, which has this email as its personal email.",
            "If you made this request, choose a new password with the button below.",
        ],
        action=EmailAction("Choose a new password", link),
        facts=[
            "This link works for one hour. If it has expired, open the RepLiT app, tap "
            "Forgot password?, and use the new link we email you.",
        ],
        notice="If you did not ask to reset your password, ignore this email: your "
        "password stays as it is. Do not forward this email, because the link lets "
        "whoever opens it set a new password.",
        reason="You are receiving this email because a password reset was requested "
        f"for {address} on RepLiT.",
    )


def verify_email(*, address: str, link: str) -> RenderedEmail:
    """A personal email added from Profile, to be confirmed."""
    return render_email(
        preheader="Confirm your personal email, so password reset links can reach you.",
        heading="Confirm your personal email",
        paragraphs=[
            f"You added this address as the personal email of the RepLiT account "
            f"{address}.",
            "Confirm it with the button below. If you ever forget your password, we "
            "will send the reset link here.",
        ],
        action=EmailAction("Confirm my email", link),
        facts=["This link works for three days."],
        notice="If you did not add this address, ignore this email and nothing changes.",
        reason="You are receiving this email because this address was added as a "
        "personal email on RepLiT.",
    )
