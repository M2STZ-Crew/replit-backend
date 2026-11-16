"""v1.12.36: fixes from the QA audit of 16 November 2026."""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import AppError, ExternalServiceError
from app.integrations.supabase_auth import SupabaseAuthClient


def _auth(status: int, body: dict[str, str]) -> tuple[httpx.AsyncClient, SupabaseAuthClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    )
    return client, SupabaseAuthClient(client)


async def test_supabase_throttling_is_a_plain_429_not_a_server_error() -> None:
    """Every sign-in reaches Supabase from this one server, so its per-IP limit
    is everyone's. When it trips, people are told to wait, not "Supabase Auth
    error" behind a 502."""
    client, auth = _auth(429, {"msg": "Request rate limit reached"})
    async with client:
        with pytest.raises(AppError) as caught:
            await auth.sign_in_with_password(email="m@x.ph", password="secret-1")
    assert caught.value.status_code == 429
    assert caught.value.error_code == "too_many_requests"
    assert "Wait a few minutes" in caught.value.message
    assert "Supabase" not in caught.value.message


async def test_other_supabase_failures_are_still_a_bad_gateway() -> None:
    client, auth = _auth(500, {"msg": "boom"})
    async with client:
        with pytest.raises(ExternalServiceError):
            await auth.sign_in_with_password(email="m@x.ph", password="secret-1")
