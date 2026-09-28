"""Setting a password from an emailed link (hermetic).

Recovery links used to open the Supabase project's default Site URL,
http://localhost:3000, and nothing anywhere let someone type a password. They
now land on /auth/reset-password, which sets it with the link's session; both
emails that carry one - "Forgot password?" and an approved affiliate's - point
there, and the reset email goes through Brevo like every other RepLiT email.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_email_client
from app.api.routes import affiliates, password_reset
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.integrations.supabase_auth import AuthError
from app.main import app


class _Auth:
    def __init__(self, *, update_error: Exception | None = None, known: bool = True) -> None:
        self.update_error = update_error
        self.known = known
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.links: list[dict[str, Any]] = []

    async def update_user(self, *, access_token: str, attributes: dict[str, Any]) -> dict:
        if self.update_error:
            raise self.update_error
        self.updates.append((access_token, attributes))
        return {"id": str(uuid4()), "email": "captain@brigade.example.com"}

    async def admin_generate_link(self, **kwargs: Any) -> dict[str, Any]:
        self.links.append(kwargs)
        if not self.known:
            raise ExternalServiceError("Supabase Auth error: User not found")
        return {"action_link": "https://auth.example.com/verify?token=abc&type=recovery"}

    async def admin_create_user(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": str(uuid4())}


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **message: Any) -> None:
        self.sent.append(message)


@pytest.fixture
def client() -> Iterator[TestClient]:
    password_reset._last_sent.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(auth: _Auth, mail: _Mail | None = None) -> None:
    app.dependency_overrides[get_auth_client] = lambda: auth
    app.dependency_overrides[get_email_client] = lambda: mail or _Mail()


_TOKEN = "eyJ" + "x" * 60


# --------------------------------------------------------------------- page --
def test_the_link_lands_on_a_page_that_asks_for_the_password(client: TestClient) -> None:
    r = client.get("/auth/reset-password")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert "Set your password" in r.text
    # The fragment is a live session: the page takes it out of the address bar.
    assert "history.replaceState" in r.text
    assert 'fetch("/auth/reset-password"' in r.text


# ---------------------------------------------------------------- set it ---
def test_the_password_is_set_with_the_links_session(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth)
    r = client.post(
        "/auth/reset-password", json={"access_token": _TOKEN, "password": "Ember-Harbor-4821!"}
    )
    assert r.status_code == 200, r.text
    assert auth.updates == [(_TOKEN, {"password": "Ember-Harbor-4821!"})]
    assert "captain@brigade.example.com" in r.json()["message"]


def test_an_expired_link_says_so(client: TestClient) -> None:
    _wire(_Auth(update_error=AuthError("Token has expired or is invalid")))
    r = client.post(
        "/auth/reset-password", json={"access_token": _TOKEN, "password": "Ember-Harbor-4821!"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "link_expired"
    assert "Forgot password?" in r.json()["message"]


def test_a_refused_password_keeps_the_link_usable(client: TestClient) -> None:
    _wire(_Auth(update_error=BadRequestError("New password should be different.")))
    r = client.post(
        "/auth/reset-password", json={"access_token": _TOKEN, "password": "Ember-Harbor-4821!"}
    )
    assert r.status_code == 422
    assert r.json()["message"] == "New password should be different."


def test_a_short_password_never_reaches_supabase(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth)
    r = client.post("/auth/reset-password", json={"access_token": _TOKEN, "password": "short"})
    assert r.status_code == 422
    assert auth.updates == []


# ------------------------------------------------------- forgot password ---
def test_forgot_password_emails_a_link_to_the_page(client: TestClient) -> None:
    auth, mail = _Auth(), _Mail()
    _wire(auth, mail)

    r = client.post("/auth/recover", json={"email": "Captain@Brigade.example.com"})

    assert r.status_code == 200
    assert auth.links == [{
        "link_type": "recovery",
        "email": "captain@brigade.example.com",
        "redirect_to": password_reset.reset_page_url(),
    }]
    assert password_reset.reset_page_url().endswith("/auth/reset-password")
    assert [m["to"] for m in mail.sent] == ["captain@brigade.example.com"]
    assert "https://auth.example.com/verify" in mail.sent[0]["html"]


def test_an_unknown_email_gets_the_same_answer_and_no_mail(client: TestClient) -> None:
    mail = _Mail()
    _wire(_Auth(known=False), mail)
    r = client.post("/auth/recover", json={"email": "nobody@brigade.example.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "If that email is registered, a reset link has been sent."
    assert mail.sent == []


def test_one_reset_email_a_minute_per_address(client: TestClient) -> None:
    auth, mail = _Auth(), _Mail()
    _wire(auth, mail)
    for _ in range(3):
        r = client.post("/auth/recover", json={"email": "a@brigade.example.com"})
        assert r.status_code == 200
    assert len(mail.sent) == 1


# ------------------------------------------------------ affiliate approval --
class _Db:
    async def execute(self, query: str, *args: Any) -> str:
        return "UPDATE 1"

    async def fetchval(self, query: str, *args: Any) -> None:
        return None


async def test_the_approval_email_links_to_the_page() -> None:
    auth, mail = _Auth(), _Mail()
    info = await affiliates._provision_subadmin(
        auth,  # type: ignore[arg-type]
        mail,  # type: ignore[arg-type]
        _Db(),  # type: ignore[arg-type]
        email="captain@brigade.example.com",
        full_name="Ramon Dizon",
        agency_type="fire_volunteer",
        org_id=uuid4(),
        org_name="Hercules Fire Brigade",
    )
    assert info["invite_email_sent"] is True
    assert auth.links[0]["redirect_to"] == password_reset.reset_page_url()
