"""Semaphore SMS client (Philippine SMS gateway) for phone verification codes.

Semaphore only sends. Unlike Twilio Verify, which this replaced, it does not
check a code afterwards, so the backend generates each code, passes it to
Semaphore's OTP route to be delivered, and keeps the check for itself (see
app/services/phone_verification.py). Semaphore can also invent the code and
echo it back; passing our own keeps the code from ever needing to be read out of
a third party's response, and keeps its length and randomness in our hands.

The OTP route is priority-routed, not rate limited, and costs two credits per
SMS (https://semaphore.co/docs). Nothing here limits how often it is called —
that is the caller's job, and it matters, because every call spends credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.exceptions import AppError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class SemaphoreNotConfiguredError(AppError):
    """Raised when an SMS is attempted without a Semaphore API key (HTTP 503)."""

    status_code = 503
    error_code = "semaphore_not_configured"


@dataclass(frozen=True)
class SentMessage:
    """What Semaphore reported back for one accepted message."""

    message_id: str | None
    status: str | None
    network: str | None


def mask_number(number: str) -> str:
    """Keep the last three digits, for logs: enough to tell numbers apart."""
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"***{digits[-3:]}" if len(digits) >= 3 else "***"


class SemaphoreClient:
    """Async client for Semaphore's OTP route."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    # Retry only when the connection never opened, so the request cannot have
    # been delivered. A read timeout or a 5xx may mean Semaphore already sent
    # the text; retrying then would send it twice and charge for it twice.
    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _post_otp(self, form: dict[str, str]) -> httpx.Response:
        url = f"{self._settings.semaphore_base_url.rstrip('/')}/otp"
        return await self._client.post(url, data=form, timeout=15.0)

    async def send_otp(self, *, number: str, code: str, message: str) -> SentMessage:
        """Deliver ``code`` to ``number``; ``message`` must contain ``{otp}``.

        ``number`` is Semaphore's own form, 639XXXXXXXXX. Raises
        SemaphoreNotConfiguredError without an API key and ExternalServiceError
        when Semaphore refuses or cannot be reached. Neither the code nor the API
        key is ever logged.
        """
        s = self._settings
        if not s.semaphore_configured:
            raise SemaphoreNotConfiguredError(
                "SMS is not configured (set SEMAPHORE_API_KEY in .env)."
            )
        if "{otp}" not in message:
            raise ValueError("The OTP message must contain the {otp} placeholder.")

        form: dict[str, str] = {
            "apikey": s.semaphore_api_key,
            "number": number,
            "message": message,
            "code": code,
        }
        if s.semaphore_sender_name:
            form["sendername"] = s.semaphore_sender_name

        try:
            response = await self._post_otp(form)
        except httpx.HTTPError as exc:
            log.error(
                "semaphore_unreachable", number=mask_number(number), error=type(exc).__name__
            )
            raise ExternalServiceError("Could not reach the SMS service.") from exc

        if _sender_name_problem(response):
            # The account has no approved Sender Name, so Semaphore refuses
            # every message. Retrying cannot fix it — only an approved name
            # (and SEMAPHORE_SENDER_NAME, if it is not the account default) can.
            log.error(
                "semaphore_no_sender_name",
                number=mask_number(number),
                status_code=response.status_code,
                body=_safe_body(response),
            )
            raise SemaphoreNotConfiguredError(
                "Semaphore has no approved Sender Name for this account yet, so it "
                "sends nothing. Register one in the Semaphore dashboard."
            )

        if response.status_code >= 400:
            log.error(
                "semaphore_rejected",
                number=mask_number(number),
                status_code=response.status_code,
                body=_safe_body(response),
            )
            raise ExternalServiceError("The SMS service refused to send the code.")

        accepted = _first_message(response)
        if accepted is None:
            log.error(
                "semaphore_unexpected_reply",
                number=mask_number(number),
                body=_safe_body(response),
            )
            raise ExternalServiceError("The SMS service did not confirm the message.")

        status = accepted.get("status")
        if isinstance(status, str) and status.lower() in ("failed", "refunded"):
            log.error("semaphore_failed", number=mask_number(number), status=status)
            raise ExternalServiceError("The SMS service could not deliver the code.")

        sent = SentMessage(
            message_id=_str_or_none(accepted.get("message_id")),
            status=_str_or_none(status),
            network=_str_or_none(accepted.get("network")),
        )
        log.info(
            "semaphore_otp_sent",
            number=mask_number(number),
            message_id=sent.message_id,
            network=sent.network,
        )
        return sent


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _first_message(response: httpx.Response) -> dict[str, Any] | None:
    """The accepted message, whether Semaphore answers with an object or a list.

    The documentation shows a single object for the OTP route while the
    ordinary send route answers with a list; both are accepted here.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, list):
        body = body[0] if body and isinstance(body[0], dict) else None
    if isinstance(body, dict) and body.get("message_id") is not None:
        return body
    return None


def _sender_name_problem(response: httpx.Response) -> bool:
    """True when Semaphore refused because of the Sender Name, not the message.

    It answers ``[{"senderName": "No active sender name found..."}]`` (seen with
    HTTP 500) or a ``sendername`` validation error; either way the key names it.
    """
    try:
        body = response.json()
    except ValueError:
        return False
    items = body if isinstance(body, list) else [body]
    return any(
        isinstance(item, dict) and any(str(k).lower() == "sendername" for k in item)
        for item in items
    )


def _safe_body(response: httpx.Response) -> str:
    """The response body for a log line, trimmed, and never echoing the code."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if k not in ("code", "message")}
    elif isinstance(body, list):
        body = [
            {k: v for k, v in item.items() if k not in ("code", "message")}
            if isinstance(item, dict) else item
            for item in body
        ]
    return str(body)[:300]
