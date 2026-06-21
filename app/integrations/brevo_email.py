"""Brevo SMTP email client (async via aiosmtplib)."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings
from app.core.exceptions import AppError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class EmailNotConfiguredError(AppError):
    """Raised when an email send runs without Brevo configuration (HTTP 503)."""

    status_code = 503
    error_code = "email_not_configured"


class BrevoEmailClient:
    """Sends transactional email through Brevo's SMTP relay."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        """Send a multipart (text + HTML) email."""
        s = self._settings
        if not s.brevo_configured:
            raise EmailNotConfiguredError(
                "Email is not configured (set BREVO_* and EMAIL_FROM in .env)."
            )
        message = EmailMessage()
        message["From"] = f"{s.email_from_name} <{s.email_from}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text or "Please view this email in an HTML-capable client.")
        message.add_alternative(html, subtype="html")
        try:
            await aiosmtplib.send(
                message,
                hostname=s.brevo_smtp_host,
                port=s.brevo_smtp_port,
                username=s.brevo_smtp_user,
                password=s.brevo_smtp_key,
                start_tls=True,
            )
        except aiosmtplib.SMTPException as exc:
            log.error("brevo_send_failed", error=str(exc))
            raise ExternalServiceError("Failed to send email.") from exc