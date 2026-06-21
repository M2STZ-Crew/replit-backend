"""Didit.me KYC client (hosted verification session + HMAC webhook).

Flow: create a verification session (POST /v2/session/), the user completes ID +
selfie/liveness on Didit's hosted UI, and Didit notifies us via an HMAC-SHA256
signed webhook carrying the decision. Transient HTTP errors are retried with
exponential backoff (tenacity).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)

_WEBHOOK_MAX_AGE_SECONDS = 300  # replay-protection window


class DiditNotConfiguredError(AppError):
    """Raised when a Didit operation runs without configuration (HTTP 503)."""

    status_code = 503
    error_code = "didit_not_configured"


class DiditKYCClient:
    """Async client for the Didit.me verification API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._settings.didit_api_key, "Content-Type": "application/json"}

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self._settings.didit_base_url.rstrip('/')}{path}"
        return await self._client.post(url, headers=self._headers, json=payload)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _get(self, path: str) -> httpx.Response:
        url = f"{self._settings.didit_base_url.rstrip('/')}{path}"
        return await self._client.get(url, headers=self._headers)

    async def create_session(
        self, *, user_id: str, callback_url: str | None = None
    ) -> dict[str, Any]:
        """Create a verification session; returns Didit's session payload (incl. url)."""
        if not self._settings.didit_configured:
            raise DiditNotConfiguredError("Didit.me is not configured (set DIDIT_* in .env).")
        payload: dict[str, Any] = {
            "workflow_id": self._settings.didit_workflow_id,
            "vendor_data": user_id,
        }
        if callback_url:
            payload["callback"] = callback_url
        try:
            resp = await self._post("/v2/session/", payload)
        except httpx.HTTPError as exc:
            log.error("didit_create_session_failed", error=str(exc))
            raise ExternalServiceError("Could not start identity verification.") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str(resp.json().get("detail") or "")
            except (ValueError, AttributeError):
                detail = resp.text[:300]
            log.warning(
                "didit_create_session_error", status_code=resp.status_code, detail=detail
            )
            if 400 <= resp.status_code < 500:
                raise BadRequestError(
                    detail or "Identity verification request was rejected.",
                    details={"didit_status": resp.status_code},
                )
            raise ExternalServiceError("Identity verification provider error.")
        data: dict[str, Any] = resp.json()
        return data

    async def retrieve_decision(self, *, session_id: str) -> dict[str, Any]:
        """Fetch the decision/status for a session."""
        try:
            resp = await self._get(f"/v2/session/{session_id}/decision/")
        except httpx.HTTPError as exc:
            log.error("didit_decision_failed", error=str(exc))
            raise ExternalServiceError("Could not retrieve verification decision.") from exc
        if resp.status_code >= 400:
            raise ExternalServiceError("Identity verification provider error.")
        data: dict[str, Any] = resp.json()
        return data

    def verify_webhook(self, *, raw_body: bytes, signature: str, timestamp: str) -> bool:
        """Verify an HMAC-SHA256 webhook signature and timestamp freshness."""
        secret = self._settings.didit_webhook_secret
        if not secret:
            log.error("didit_webhook_secret_missing")
            return False
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False
        if abs(int(time.time()) - ts) > _WEBHOOK_MAX_AGE_SECONDS:
            log.warning("didit_webhook_stale", timestamp=timestamp)
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")