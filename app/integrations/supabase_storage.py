"""Supabase Storage client (service_role).

Uploads and signs private objects (e.g. National ID + selfie in the national-ids
bucket). Uses the service_role key, so it bypasses Storage RLS; clients receive
short-lived signed URLs. Object path convention: '<user_id>/<filename>'.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class SupabaseStorageClient:
    """Async client for the Supabase Storage REST API (server-side, service_role)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        return {"apikey": key, "Authorization": f"Bearer {key}"}

    async def upload(
        self,
        *,
        bucket: str,
        path: str,
        content: bytes,
        content_type: str,
        upsert: bool = True,
    ) -> str:
        """Upload bytes to ``bucket/path``; returns the object path."""
        url = f"{self._settings.storage_url}/object/{bucket}/{path}"
        headers = {**self._headers, "Content-Type": content_type}
        if upsert:
            headers["x-upsert"] = "true"
        try:
            resp = await self._client.post(url, headers=headers, content=content)
        except httpx.HTTPError as exc:
            log.error("storage_upload_failed", bucket=bucket, error=str(exc))
            raise ExternalServiceError("File upload failed.") from exc
        if resp.status_code >= 400:
            log.warning(
                "storage_upload_error", bucket=bucket, status_code=resp.status_code,
                body=resp.text[:300],
            )
            raise ExternalServiceError("Storage rejected the upload.")
        return path

    async def create_signed_url(self, *, bucket: str, path: str, expires_in: int = 3600) -> str:
        """Return a time-limited signed URL for a private object."""
        url = f"{self._settings.storage_url}/object/sign/{bucket}/{path}"
        try:
            resp = await self._client.post(
                url,
                headers={**self._headers, "Content-Type": "application/json"},
                json={"expiresIn": expires_in},
            )
        except httpx.HTTPError as exc:
            log.error("storage_sign_failed", error=str(exc))
            raise ExternalServiceError("Could not create signed URL.") from exc
        if resp.status_code >= 400:
            raise ExternalServiceError("Storage could not sign the object.")
        data: dict[str, Any] = resp.json()
        signed = data.get("signedURL") or data.get("signedUrl") or ""
        return f"{self._settings.storage_url}{signed}"

    async def remove(self, *, bucket: str, path: str) -> None:
        """Delete an object (no-op tolerated for 404)."""
        url = f"{self._settings.storage_url}/object/{bucket}/{path}"
        try:
            resp = await self._client.delete(url, headers=self._headers)
        except httpx.HTTPError as exc:
            log.error("storage_remove_failed", error=str(exc))
            raise ExternalServiceError("Could not delete object.") from exc
        if resp.status_code >= 400 and resp.status_code != 404:
            raise ExternalServiceError("Storage delete error.")