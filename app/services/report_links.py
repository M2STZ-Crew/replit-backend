"""Short-lived links to download an incident's PDF from a browser (v1.12.5).

The app opens the PDF in the phone's browser so it lands in Downloads. A
browser sends no Authorization header, so the app first asks for a link
(``POST /incidents/{id}/report-link``, signed-in and visibility-checked) and
the link carries a signature instead: who it was made for, for which
incident, until when. It works for five minutes, for that incident only, and
the download checks again that the person may still see the incident.

The signature is an HMAC under a key derived from the server's JWT secret, the
way phone codes are protected — nothing is stored. A server without the JWT
secret (it is only a fallback for token checks) derives it from the
service-role key instead; both stay on the server.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import get_settings

LINK_TTL = timedelta(minutes=5)


class InvalidReportLinkError(ValueError):
    """A link that was tampered with, made for another incident, or malformed."""


class ExpiredReportLinkError(ValueError):
    """A genuine link whose five minutes are up."""


def _key() -> bytes:
    settings = get_settings()
    secret = settings.supabase_jwt_secret or settings.supabase_service_role_key
    if not secret:
        raise RuntimeError("A server secret is required to sign report links.")
    return hmac.new(secret.encode(), b"replit/report-link/v1", hashlib.sha256).digest()


def _signature(area_id: UUID, user_id: UUID, expires: int) -> str:
    message = f"{area_id}.{user_id}.{expires}".encode()
    digest = hmac.new(_key(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign_report_link(
    area_id: UUID, user_id: UUID, *, now: datetime | None = None
) -> tuple[str, datetime]:
    """A token for ``area_id``'s PDF, made for ``user_id``, and when it expires."""
    expires_at = (now or datetime.now(UTC)) + LINK_TTL
    expires = int(expires_at.timestamp())
    token = f"{user_id.hex}.{expires}.{_signature(area_id, user_id, expires)}"
    return token, datetime.fromtimestamp(expires, UTC)


def verify_report_link(area_id: UUID, token: str, *, now: datetime | None = None) -> UUID:
    """The user the link was made for, if it is genuine, for this incident and in time."""
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidReportLinkError("Malformed link.")
    user_hex, expires_raw, signature = parts
    try:
        user_id = UUID(hex=user_hex)
        expires = int(expires_raw)
    except ValueError as exc:
        raise InvalidReportLinkError("Malformed link.") from exc
    if not hmac.compare_digest(signature, _signature(area_id, user_id, expires)):
        raise InvalidReportLinkError("This link is not valid for this report.")
    if (now or datetime.now(UTC)).timestamp() > expires:
        raise ExpiredReportLinkError("This download link has expired.")
    return user_id
