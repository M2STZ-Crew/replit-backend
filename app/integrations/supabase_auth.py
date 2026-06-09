"""Supabase Auth (GoTrue) HTTP client.

Thin async wrapper over the GoTrue REST API: citizen self-signup, login, token
refresh, current-user lookup, logout, and admin user management. Public auth flows
use the anon key; admin operations use the service_role key (server-side only).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class AuthError(AppError):
    """Authentication failure surfaced from GoTrue (HTTP 401)."""

    status_code = 401
    error_code = "auth_error"


class SupabaseAuthClient:
    """Async client for the Supabase GoTrue REST API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()

    @property
    def _anon_headers(self) -> dict[str, str]:
        return {
            "apikey": self._settings.supabase_anon_key,
            "Content-Type": "application/json",
        }

    @property
    def _admin_headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._settings.gotrue_url}{path}"
        try:
            response = await self._client.request(
                method, url, headers=headers, json=json, params=params
            )
        except httpx.HTTPError as exc:
            log.error("gotrue_request_failed", path=path, error=str(exc))
            raise ExternalServiceError("Supabase Auth request failed.") from exc

        if response.status_code >= 400:
            self._raise_for_error(response)
        if not response.content:
            return {}
        result: dict[str, Any] = response.json()
        return result

    def _raise_for_error(self, response: httpx.Response) -> None:
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = (
            body.get("msg")
            or body.get("message")
            or body.get("error_description")
            or body.get("error")
            or "Supabase Auth error"
        )
        code = response.status_code
        log.warning("gotrue_error", status_code=code, message=str(message))
        if code == 422:
            raise BadRequestError(str(message), details={"gotrue_status": code})
        if code in (400, 401, 403):
            raise AuthError(str(message), details={"gotrue_status": code})
        raise ExternalServiceError(f"Supabase Auth error: {message}")

    # ----- Public flows (anon key) -----
    async def sign_up(
        self, *, email: str, password: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Citizen self-signup. `data` becomes auth user_metadata (e.g. full_name)."""
        payload: dict[str, Any] = {"email": email, "password": password}
        if data:
            payload["data"] = data
        return await self._request("POST", "/signup", headers=self._anon_headers, json=payload)

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        """Email/password login; returns a session (access + refresh tokens)."""
        return await self._request(
            "POST",
            "/token",
            headers=self._anon_headers,
            json={"email": email, "password": password},
            params={"grant_type": "password"},
        )

    async def refresh_session(self, *, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for a new session."""
        return await self._request(
            "POST",
            "/token",
            headers=self._anon_headers,
            json={"refresh_token": refresh_token},
            params={"grant_type": "refresh_token"},
        )

    async def get_user(self, *, access_token: str) -> dict[str, Any]:
        """Fetch the GoTrue user for an access token."""
        headers = {**self._anon_headers, "Authorization": f"Bearer {access_token}"}
        return await self._request("GET", "/user", headers=headers)

    async def sign_out(self, *, access_token: str) -> None:
        """Revoke the session for the given access token."""
        headers = {**self._anon_headers, "Authorization": f"Bearer {access_token}"}
        await self._request("POST", "/logout", headers=headers)

    # ----- Admin flows (service_role key) -----
    async def admin_create_user(
        self,
        *,
        email: str,
        password: str | None = None,
        phone: str | None = None,
        email_confirm: bool = True,
        user_metadata: dict[str, Any] | None = None,
        app_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Admin-create a confirmed user (used by the admin-creates-user flow, Part 5)."""
        payload: dict[str, Any] = {"email": email, "email_confirm": email_confirm}
        if password is not None:
            payload["password"] = password
        if phone is not None:
            payload["phone"] = phone
        if user_metadata is not None:
            payload["user_metadata"] = user_metadata
        if app_metadata is not None:
            payload["app_metadata"] = app_metadata
        return await self._request(
            "POST", "/admin/users", headers=self._admin_headers, json=payload
        )

    async def admin_update_user(
        self, *, user_id: str, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        """Admin-update an auth user (e.g. metadata, password)."""
        return await self._request(
            "PUT", f"/admin/users/{user_id}", headers=self._admin_headers, json=attributes
        )

    async def admin_delete_user(self, *, user_id: str) -> None:
        """Admin-delete an auth user (cascades to public.users via FK)."""
        await self._request(
            "DELETE", f"/admin/users/{user_id}", headers=self._admin_headers
        )