"""v1.12.36: fixes from the QA audit of 16 November 2026."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_database
from app.core.exceptions import AppError, ExternalServiceError
from app.integrations.supabase_auth import AuthError, SupabaseAuthClient
from app.main import app
from app.services import password_attempts

RIGHT = "right-password"
USER = uuid4()


class _Auth:
    """Supabase Auth, as far as a password check needs it."""

    def __init__(self) -> None:
        self.sign_ins: list[tuple[str, str]] = []

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        self.sign_ins.append((email, password))
        if password != RIGHT:
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        return {
            "access_token": "access",
            "refresh_token": "refresh",
            "user": {"id": str(USER), "email": email},
        }

    async def sign_out(self, *, access_token: str, scope: str | None = None) -> None:
        return None

    async def update_user(self, *, access_token: str, attributes: dict[str, Any]) -> Any:
        return {"id": str(USER), "email": "maria@example.com"}


class _Db:
    """Maria verified her number; nobody is frozen; everyone is a resident."""

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "deletion_requested_at" in query:
            return None
        if "phone_verified" in query:
            return {"+639171234567": "maria@example.com"}.get(args[0])
        if "role" in query:
            return "general_user"
        return None


@pytest.fixture
def auth() -> Iterator[_Auth]:
    fake = _Auth()
    app.dependency_overrides[get_auth_client] = lambda: fake
    app.dependency_overrides[get_database] = lambda: _Db()
    with TestClient(app):
        yield fake
    app.dependency_overrides.clear()


def _login(email: str = "maria@example.com", password: str = "wrong") -> httpx.Response:
    with TestClient(app) as client:
        return client.post("/auth/login", json={"email": email, "password": password})


def test_five_wrong_passwords_and_the_account_waits(auth: _Auth) -> None:
    for _ in range(password_attempts.MAX_WRONG):
        assert _login().status_code == 401
    asked = len(auth.sign_ins)

    locked = _login(password=RIGHT)  # even the right one, while it waits
    assert locked.status_code == 429, locked.text
    body = locked.json()
    assert body["error"] == "too_many_attempts"
    assert "Wait 15 minutes" in body["message"]
    assert "reset your password" in body["message"]
    assert 0 < body["details"]["retry_after_seconds"] <= password_attempts.WINDOW_SECONDS
    assert len(auth.sign_ins) == asked, "a locked account never reaches Supabase"

    # Someone else's account is not touched.
    assert _login("jose@example.com", RIGHT).status_code == 200


def test_the_right_password_starts_the_count_again(auth: _Auth) -> None:
    for _ in range(password_attempts.MAX_WRONG - 1):
        assert _login().status_code == 401
    assert _login(password=RIGHT).status_code == 200
    for _ in range(password_attempts.MAX_WRONG - 1):
        assert _login().status_code == 401
    assert _login(password=RIGHT).status_code == 200


def test_the_wait_ends_after_15_minutes(auth: _Auth, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(password_attempts, "_clock", lambda: now[0])
    for _ in range(password_attempts.MAX_WRONG):
        _login()
    now[0] += 14 * 60
    late = _login(password=RIGHT)
    assert late.status_code == 429
    assert "Wait 1 minute," in late.json()["message"]
    now[0] += 60
    assert _login(password=RIGHT).status_code == 200


def test_the_email_and_the_verified_number_share_one_count(auth: _Auth) -> None:
    with TestClient(app) as client:
        for i in range(password_attempts.MAX_WRONG):
            if i % 2:
                json: dict[str, str] = {"email": "Maria@Example.com", "password": "x"}
            else:
                json = {"phone": "0917 123 4567", "password": "x"}
            assert client.post("/auth/login", json=json).status_code == 401
        by_phone = client.post("/auth/login", json={"phone": "09171234567", "password": RIGHT})
    assert by_phone.status_code == 429


def test_an_unknown_number_locks_just_as_a_known_one(auth: _Auth) -> None:
    """Waiting says nothing about which numbers are registered."""
    with TestClient(app) as client:
        for typed in ("09171234567", "09181234567"):
            for _ in range(password_attempts.MAX_WRONG):
                assert client.post(
                    "/auth/login", json={"phone": typed, "password": "x"}
                ).status_code == 401
            assert client.post(
                "/auth/login", json={"phone": typed, "password": RIGHT}
            ).status_code == 429


def test_the_residents_site_shares_the_count(auth: _Auth) -> None:
    with TestClient(app) as client:
        for _ in range(password_attempts.MAX_WRONG):
            wrong = client.post(
                "/auth/restore", json={"email": "maria@example.com", "password": "x"}
            )
            assert wrong.status_code == 400
            assert wrong.json()["error"] == "wrong_password"
        locked = client.post(
            "/auth/delete", json={"email": "maria@example.com", "password": RIGHT}
        )
    assert locked.status_code == 429
    assert locked.json()["error"] == "too_many_attempts"
    assert _login(password=RIGHT).status_code == 429


def test_a_new_password_from_a_reset_link_ends_the_wait(auth: _Auth) -> None:
    for _ in range(password_attempts.MAX_WRONG):
        _login()
    assert _login(password=RIGHT).status_code == 429
    with TestClient(app) as client:
        reset = client.post(
            "/auth/reset-password",
            json={"access_token": "a" * 40, "password": "a-new-password-2026"},
        )
    assert reset.status_code == 200, reset.text
    assert _login(password=RIGHT).status_code == 200


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
