"""Twilio Verify client for phone OTP (+40% verification).

Wraps Twilio's synchronous SDK in a worker thread so it stays non-blocking. Using
Twilio Verify means OTP generation, delivery, expiry, and rate-limiting are managed
by Twilio — we never store or hash codes ourselves.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class TwilioNotConfiguredError(AppError):
    """Raised when a Twilio operation runs without Twilio credentials (HTTP 503)."""

    status_code = 503
    error_code = "twilio_not_configured"


@lru_cache(maxsize=1)
def _client() -> Client:
    """Return a cached Twilio REST client; raises if Twilio isn't configured."""
    settings = get_settings()
    if not settings.twilio_configured:
        raise TwilioNotConfiguredError("Twilio is not configured (set TWILIO_* in .env).")
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


class TwilioVerifyClient:
    """Async wrapper around Twilio Verify start/check operations."""

    def __init__(self) -> None:
        self._service_sid = get_settings().twilio_verify_service_sid

    async def start_verification(self, phone: str) -> str:
        """Send an SMS verification code to `phone`; returns the Twilio status."""

        def _send() -> str:
            verification = (
                _client()
                .verify.v2.services(self._service_sid)
                .verifications.create(to=phone, channel="sms")
            )
            return str(verification.status)

        try:
            return await asyncio.to_thread(_send)
        except TwilioRestException as exc:
            if getattr(exc, "status", None) == 400:
                raise BadRequestError("Invalid phone number.") from exc
            log.error("twilio_start_failed", error=str(exc))
            raise ExternalServiceError("Could not send verification code.") from exc

    async def check_verification(self, phone: str, code: str) -> bool:
        """Check a submitted code; returns True if Twilio reports 'approved'."""

        def _check() -> bool:
            result = (
                _client()
                .verify.v2.services(self._service_sid)
                .verification_checks.create(to=phone, code=code)
            )
            return bool(result.status == "approved")

        try:
            return await asyncio.to_thread(_check)
        except TwilioRestException as exc:
            if getattr(exc, "status", None) == 404:
                raise BadRequestError(
                    "Verification code expired or not found; request a new one."
                ) from exc
            log.error("twilio_check_failed", error=str(exc))
            raise ExternalServiceError("Phone verification failed.") from exc