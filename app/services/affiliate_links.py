"""Signed links for an affiliate's applicant (v1.12.53).

* **certificate**: the public form uploads its SEC certificate right after the
  application is stored (one hour), and only for that application.
* **admin**: an accepted organization's contact sets up its Admin sign-in in
  the console (48 hours, once: it is used up when the organization has an
  Admin).

Each token says what it is for, for which application or organization, and
until when; the contact's email rides along for the Admin link. The key is
derived from the service-role key, which only this server holds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from app.core.config import get_settings

Purpose = Literal["certificate", "admin"]

CERTIFICATE_FOR = timedelta(hours=1)
ADMIN_FOR = timedelta(hours=48)


class AffiliateLinkError(ValueError):
    """A token that is not ours or not for this."""


@dataclass(frozen=True)
class AffiliateLink:
    subject: UUID
    email: str
    expires_at: int
    expired: bool


def _key() -> bytes:
    secret = get_settings().supabase_service_role_key or ""
    return hashlib.sha256(b"replit-affiliate-link:" + secret.encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(
    subject: UUID,
    purpose: Purpose,
    lasts: timedelta,
    *,
    email: str = "",
    now: float | None = None,
) -> str:
    at = time.time() if now is None else now
    body = json.dumps(
        {
            "s": str(subject),
            "p": purpose,
            "e": email.strip().lower(),
            "x": int(at + lasts.total_seconds()),
        },
        separators=(",", ":"),
    ).encode()
    payload = _b64(body)
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str, purpose: Purpose, *, now: float | None = None) -> AffiliateLink:
    """What the token is for; ``expired`` rather than an error once out of date,
    so a page can say the link has expired. Raises :class:`AffiliateLinkError`."""
    try:
        payload, sig = token.split(".", 1)
        want = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise AffiliateLinkError("Not one of ours.")
        body = json.loads(_unb64(payload))
        if body["p"] != purpose:
            raise AffiliateLinkError("Not for this.")
        expires = int(body["x"])
        return AffiliateLink(
            subject=UUID(str(body["s"])),
            email=str(body.get("e") or ""),
            expires_at=expires,
            expired=(time.time() if now is None else now) > expires,
        )
    except AffiliateLinkError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise AffiliateLinkError("Not one of ours.") from exc
