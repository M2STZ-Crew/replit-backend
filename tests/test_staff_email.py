"""A staff member's personal email (hermetic, 6 Nov 2026).

What these pin:
- a link's token says whose account, the address it went to, what it does and
  until when, and nothing else passes: not a changed signature, another
  purpose, or an old one;
- the emailed password link confirms the personal email, then opens the
  set-password page through a fresh recovery link, and does nothing for an
  account that no longer has that address or is turned off;
- the verify link confirms a personal email added from Profile;
- only coordinators and responders set one, never an @replit.com address, and
  a link to confirm it goes there.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_current_user, get_database, get_email_client
from app.api.routes import staff_email
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services.staff_links import (
    LinkError,
    make_token,
    password_link,
    read_token,
    verify_link,
)

ADDRESS = "obryan.fircor@replit.com"
PERSONAL = "odyssey.bryan@gmail.com"


# --------------------------------------------------------------------------- #
# The token
# --------------------------------------------------------------------------- #
def test_a_token_says_whose_account_and_where_it_went() -> None:
    uid = uuid4()
    token = make_token(uid, "Odyssey.Bryan@Gmail.com", "password", timedelta(hours=1))
    assert read_token(token, "password") == (uid, PERSONAL)


def test_nothing_else_passes() -> None:
    uid = uuid4()
    token = make_token(uid, PERSONAL, "password", timedelta(hours=1))
    payload, sig = token.split(".")
    for bad in (f"{payload}.{sig[:-2]}xx", f"{payload}x.{sig}", "not-a-token", ""):
        with pytest.raises(LinkError):
            read_token(bad, "password")
    with pytest.raises(LinkError):
        read_token(token, "verify")
    old = make_token(uid, PERSONAL, "password", timedelta(hours=1), now=0)
    with pytest.raises(LinkError):
        read_token(old, "password")


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
class _Db:
    def __init__(self, **user: Any) -> None:
        self.user: dict[str, Any] = {
            "email": ADDRESS,
            "personal_email": PERSONAL,
            "personal_email_verified_at": None,
            "is_active": True,
            **user,
        }
        self.updates: list[str] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        return dict(self.user)

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        self.updates.append(q)
        if "set personal_email_verified_at" in q:
            self.user["personal_email_verified_at"] = datetime.now(UTC)
        elif "set personal_email = $2" in q:
            self.user["personal_email"] = args[1]
            self.user["personal_email_verified_at"] = None
        return "UPDATE 1"


class _Auth:
    def __init__(self) -> None:
        self.links: list[dict[str, Any]] = []

    async def admin_generate_link(self, **kwargs: Any) -> dict[str, Any]:
        self.links.append(kwargs)
        return {"action_link": "https://auth.example.com/verify?token=fresh&type=recovery"}


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **message: Any) -> None:
        self.sent.append(message)


@pytest.fixture
def client() -> Iterator[TestClient]:
    staff_email._last_verify.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, auth: _Auth | None = None, mail: _Mail | None = None) -> None:
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_auth_client] = lambda: auth or _Auth()
    app.dependency_overrides[get_email_client] = lambda: mail or _Mail()


def _path(link: str) -> str:
    return "/" + link.split("://", 1)[1].split("/", 1)[1]


def test_the_password_link_confirms_then_opens_the_page(client: TestClient) -> None:
    db, auth = _Db(), _Auth()
    _wire(db, auth)
    uid = uuid4()
    link = password_link(uid, PERSONAL, timedelta(days=3))

    r = client.get(_path(link), follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"].startswith("https://auth.example.com/verify")
    assert db.user["personal_email_verified_at"] is not None
    assert auth.links[0]["email"] == ADDRESS
    assert auth.links[0]["link_type"] == "recovery"
    assert auth.links[0]["redirect_to"].endswith("/auth/reset-password")


@pytest.mark.parametrize(
    "user", [{"personal_email": "someone.else@gmail.com"}, {"is_active": False}]
)
def test_the_password_link_does_nothing_for_another_address_or_a_closed_account(
    client: TestClient, user: dict[str, Any]
) -> None:
    db, auth = _Db(**user), _Auth()
    _wire(db, auth)
    r = client.get(_path(password_link(uuid4(), PERSONAL, timedelta(hours=1))))
    assert r.status_code == 400
    assert "This link has expired" in r.text
    assert auth.links == [] and db.updates == []


def test_the_verify_link_confirms_the_address(client: TestClient) -> None:
    db = _Db()
    _wire(db)
    r = client.get(_path(verify_link(uuid4(), PERSONAL)))
    assert r.status_code == 200
    assert "Your email is confirmed" in r.text
    assert db.user["personal_email_verified_at"] is not None


def _staff(role: str = "response_team") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role=role, email=ADDRESS, agency_type="fire_volunteer",
        phone_verified=True,
    )


def test_staff_set_their_own_and_a_link_goes_there(client: TestClient) -> None:
    db, mail = _Db(personal_email=None), _Mail()
    _wire(db, mail=mail)
    user = _staff()
    app.dependency_overrides[get_current_user] = lambda: user

    r = client.put("/auth/me/personal-email", json={"email": "New.Me@Gmail.com"})

    assert r.status_code == 200, r.text
    assert r.json()["message"] == "We sent a link to new.me@gmail.com. Open it to confirm."
    assert db.user["personal_email"] == "new.me@gmail.com"
    (sent,) = mail.sent
    assert sent["to"] == "new.me@gmail.com"
    assert "/auth/personal-email/verify?token=" in sent["text"]
    token = sent["text"].split("token=", 1)[1].split()[0]
    assert read_token(token, "verify") == (user.id, "new.me@gmail.com")


def test_a_confirmed_address_is_not_sent_again(client: TestClient) -> None:
    db, mail = _Db(personal_email_verified_at=datetime.now(UTC)), _Mail()
    _wire(db, mail=mail)
    app.dependency_overrides[get_current_user] = lambda: _staff("sub_admin")
    r = client.put("/auth/me/personal-email", json={"email": PERSONAL})
    assert r.json()["message"] == "That email is already confirmed."
    assert mail.sent == []


def test_not_a_replit_address_and_not_for_residents(client: TestClient) -> None:
    db = _Db()
    _wire(db)
    app.dependency_overrides[get_current_user] = lambda: _staff()
    r = client.put("/auth/me/personal-email", json={"email": "x.firres@replit.com"})
    assert r.status_code == 400 and r.json()["error"] == "not_personal"

    app.dependency_overrides[get_current_user] = lambda: _staff("general_user")
    r = client.put("/auth/me/personal-email", json={"email": "me@gmail.com"})
    assert r.status_code == 403
    assert db.updates == []


def test_me_carries_the_personal_email() -> None:
    fields = AuthenticatedUser.model_fields
    assert "personal_email" in fields and "personal_email_verified" in fields
