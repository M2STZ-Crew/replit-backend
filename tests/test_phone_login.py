"""Signing up with a mobile number, and logging in with one (hermetic).

Supabase Auth keeps accounts by email, so logging in by number means finding
the account that *verified* that number and signing in as it. These pin:
- a verified number signs in as its own account, and only a verified one;
- a number no account verified is refused exactly as a wrong password is, and
  never reaches Supabase — so the login cannot be used to test which numbers
  are registered;
- sign-up stores the number in one form, and refuses a malformed or already
  claimed number *before* the account is made, so no account is left behind
  that could never pass the phone gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_database
from app.integrations.supabase_auth import AuthError
from app.main import app

USER = uuid4()
RIGHT = "right-password"


class _Auth:
    """Supabase Auth, as far as login and signup need it."""

    def __init__(self) -> None:
        self.sign_ins: list[tuple[str, str]] = []
        self.sign_ups: list[str] = []

    def _session(self, email: str) -> dict[str, Any]:
        return {
            "access_token": "access",
            "refresh_token": "refresh",
            "user": {"id": str(USER), "email": email},
        }

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        self.sign_ins.append((email, password))
        if password != RIGHT:
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        return self._session(email)

    async def sign_up(
        self, *, email: str, password: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.sign_ups.append(email)
        return self._session(email)


class _Db:
    """Knows which numbers are verified, and by whose account."""

    def __init__(self, verified: dict[str, str] | None = None) -> None:
        self.verified = verified or {}
        self.lookups: list[str] = []
        self.updates: list[tuple[Any, ...]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert "phone_verified" in query, "only a verified number may identify an account"
        self.lookups.append(args[0])
        return self.verified.get(args[0])

    async def execute(self, query: str, *args: Any) -> str:
        self.updates.append(args)
        return "UPDATE 1"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(auth: _Auth, db: _Db) -> None:
    app.dependency_overrides[get_auth_client] = lambda: auth
    app.dependency_overrides[get_database] = lambda: db


MARIA = {"+639171234567": "maria@example.com"}


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("typed", ["0917 123 4567", "09171234567", "+63 917-123-4567"])
def test_a_verified_number_signs_in_as_its_account(client: TestClient, typed: str) -> None:
    auth, db = _Auth(), _Db(MARIA)
    _wire(auth, db)
    response = client.post("/auth/login", json={"phone": typed, "password": RIGHT})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "maria@example.com"
    assert auth.sign_ins == [("maria@example.com", RIGHT)]
    assert db.lookups == ["+639171234567"]


def test_an_unknown_number_reads_exactly_like_a_wrong_password(client: TestClient) -> None:
    auth, db = _Auth(), _Db(MARIA)
    _wire(auth, db)
    wrong_password = client.post(
        "/auth/login", json={"phone": "09171234567", "password": "nope"}
    )
    unknown_number = client.post(
        "/auth/login", json={"phone": "09181234567", "password": "nope"}
    )
    assert wrong_password.status_code == unknown_number.status_code == 401
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(unknown_number) == strip(wrong_password)
    assert len(auth.sign_ins) == 1, "the unknown number never reached Supabase"


def test_a_malformed_number_is_a_400(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth, _Db(MARIA))
    response = client.post("/auth/login", json={"phone": "0281234567", "password": RIGHT})
    assert response.status_code == 400
    assert auth.sign_ins == []


def test_email_still_signs_in(client: TestClient) -> None:
    """Staff have no verified number; they keep their email."""
    auth, db = _Auth(), _Db()
    _wire(auth, db)
    response = client.post(
        "/auth/login", json={"email": "captain@example.com", "password": RIGHT}
    )
    assert response.status_code == 200
    assert auth.sign_ins == [("captain@example.com", RIGHT)]
    assert db.lookups == []


@pytest.mark.parametrize(
    "body",
    [
        {"password": RIGHT},
        {"email": "a@example.com", "phone": "09171234567", "password": RIGHT},
    ],
)
def test_exactly_one_way_to_say_who_you_are(client: TestClient, body: dict[str, str]) -> None:
    auth = _Auth()
    _wire(auth, _Db(MARIA))
    assert client.post("/auth/login", json=body).status_code == 422
    assert auth.sign_ins == []


# --------------------------------------------------------------------------- #
# Signup
# --------------------------------------------------------------------------- #
def _signup(client: TestClient, mobile: str) -> Any:
    return client.post(
        "/auth/signup",
        json={
            "email": "juan@example.com",
            "password": "long-enough-1",
            "full_name": "Juan dela Cruz",
            "mobile": mobile,
        },
    )


def test_signup_stores_the_number_in_one_form(client: TestClient) -> None:
    auth, db = _Auth(), _Db()
    _wire(auth, db)
    response = _signup(client, "0917 123 4567")
    assert response.status_code == 201, response.text
    assert auth.sign_ups == ["juan@example.com"]
    [update] = db.updates
    assert update[1] == "+639171234567"


def test_signup_refuses_a_claimed_number_before_making_the_account(
    client: TestClient,
) -> None:
    auth = _Auth()
    _wire(auth, _Db(MARIA))
    response = _signup(client, "09171234567")
    assert response.status_code == 409
    assert response.json()["error"] == "phone_number_taken"
    assert auth.sign_ups == [], "no account left behind that could never verify"


def test_signup_refuses_a_malformed_number_before_making_the_account(
    client: TestClient,
) -> None:
    auth = _Auth()
    _wire(auth, _Db())
    response = _signup(client, "12345")
    assert response.status_code == 400
    assert auth.sign_ups == []
