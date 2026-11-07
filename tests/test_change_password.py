"""POST /auth/me/password: change my password, for every role.

The current password is checked by signing in with it; the new one is set
with the service key; every other session is revoked and this one kept. A
wrong current password is a 400 — never a 401, which the clients would read
as an expired session and sign the person out.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_access_token, get_auth_client, get_current_user
from app.core.exceptions import ExternalServiceError
from app.integrations.supabase_auth import AuthError
from app.main import app
from app.schemas.auth import AuthenticatedUser

CURRENT = "old-password-1"
NEW = "new-password-2"


class _Auth:
    """Supabase Auth as far as this endpoint uses it."""

    def __init__(self, *, sign_out_fails: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sign_out_fails = sign_out_fails

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        self.calls.append(("sign_in", {"email": email, "password": password}))
        if password != CURRENT:
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        return {"access_token": "check-session", "refresh_token": "r"}

    async def admin_update_user(
        self, *, user_id: str, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("update", {"user_id": user_id, **attributes}))
        return {"id": user_id}

    async def sign_out(self, *, access_token: str, scope: str | None = None) -> None:
        self.calls.append(("sign_out", {"token": access_token, "scope": scope}))
        if self.sign_out_fails:
            raise ExternalServiceError("Supabase Auth request failed.")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(auth: _Auth, *, role: str = "general_user", email: str | None = "m@x.ph") -> str:
    user = AuthenticatedUser(id=uuid4(), role=role, email=email)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_access_token] = lambda: "this-session"
    app.dependency_overrides[get_auth_client] = lambda: auth
    return str(user.id)


def _change(client: TestClient, current: str = CURRENT, new: str = NEW) -> Any:
    return client.post("/auth/me/password", json={"current_password": current, "new_password": new})


@pytest.mark.parametrize("role", ["general_user", "response_team", "sub_admin", "admin"])
def test_the_password_changes_and_only_this_device_stays_signed_in(
    client: TestClient, role: str
) -> None:
    auth = _Auth()
    user_id = _wire(auth, role=role)
    response = _change(client)
    assert response.status_code == 204
    assert auth.calls == [
        ("sign_in", {"email": "m@x.ph", "password": CURRENT}),
        ("update", {"user_id": user_id, "password": NEW}),
        ("sign_out", {"token": "this-session", "scope": "others"}),
    ]


def test_a_wrong_current_password_is_a_400_and_changes_nothing(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth)
    response = _change(client, current="not-it")
    assert response.status_code == 400
    assert response.json()["error"] == "wrong_password"
    assert [name for name, _ in auth.calls] == ["sign_in"]


def test_the_same_password_again_is_refused_before_asking_supabase(
    client: TestClient,
) -> None:
    auth = _Auth()
    _wire(auth)
    response = _change(client, new=CURRENT)
    assert response.status_code == 400
    assert response.json()["error"] == "same_password"
    assert auth.calls == []


@pytest.mark.parametrize("new", ["short", "x" * 129])
def test_the_new_password_follows_the_sign_up_rule(client: TestClient, new: str) -> None:
    auth = _Auth()
    _wire(auth)
    assert _change(client, new=new).status_code == 422
    assert auth.calls == []


def test_the_change_stands_when_the_other_sessions_cannot_be_revoked(
    client: TestClient,
) -> None:
    auth = _Auth(sign_out_fails=True)
    _wire(auth)
    assert _change(client).status_code == 204
    assert ("update", {"user_id": auth.calls[1][1]["user_id"], "password": NEW}) in auth.calls


def test_it_needs_a_session(client: TestClient) -> None:
    app.dependency_overrides[get_auth_client] = _Auth
    assert _change(client).status_code == 401
