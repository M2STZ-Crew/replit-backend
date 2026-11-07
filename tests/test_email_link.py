"""A resident's email link (hermetic, 7 Nov 2026).

Since app 1.12.29 the link is how a resident's sign-up ends, in place of a
texted code. What these pin:
- asking sends one email with a one-time link, and says when Send again opens;
- a second ask inside the wait, or past the day's allowance, is refused with
  how long to wait, and sends nothing;
- a failed send records nothing, so it spends neither the wait nor the day;
- an address already confirmed gets no email and stays confirmed (until
  v1.12.22 asking again set it back to pending);
- the link lands on a page in every case, never JSON: confirmed, already
  confirmed, expired, or replaced by a newer link.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database, get_email_client
from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.main import app
from app.schemas.auth import AuthenticatedUser

ADDRESS = "juan.delacruz@gmail.com"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "require_citizen_phone_verification", False)
    monkeypatch.setattr(s, "public_base_url", "https://api.example.com")
    monkeypatch.setattr(s, "email_link_resend_cooldown_seconds", 60)
    monkeypatch.setattr(s, "email_link_daily_limit_per_user", 5)
    monkeypatch.setattr(s, "email_verification_percent", 10)


# --------------------------------------------------------------------------- #
# An in-memory user_verifications that honours rollback
# --------------------------------------------------------------------------- #
class _Db:
    def __init__(self) -> None:
        # user id -> {"id", "status", "metadata", "percent_awarded"}
        self.rows: dict[UUID, dict[str, Any]] = {}

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = copy.deepcopy(self.rows)
        try:
            yield
        except BaseException:
            self.rows = snapshot
            raise

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if "where user_id = $1 and type = 'email'" in q:
            row = self.rows.get(args[0])
            if row is None:
                return None
            return {"status": row["status"], "sends": json.dumps(row["metadata"].get("sends", []))}
        if "metadata->>'token_hash' = $1" in q:
            for row in self.rows.values():
                if row["metadata"].get("token_hash") == args[0]:
                    expires = row["metadata"].get("expires_at")
                    return {
                        "id": row["id"],
                        "status": row["status"],
                        "expires_at": datetime.fromisoformat(expires) if expires else None,
                    }
            return None
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if "pg_advisory_xact_lock" in q:
            return "SELECT 1"
        if q.startswith("insert into public.user_verifications"):
            user_id, meta = args[0], json.loads(args[1])
            row = self.rows.get(user_id)
            if row is None:
                self.rows[user_id] = {
                    "id": uuid4(),
                    "status": "pending",
                    "metadata": meta,
                    "percent_awarded": 0,
                }
            else:
                row["metadata"] = {**row["metadata"], **meta}
                row["status"] = "pending"
            return "INSERT 0 1"
        if "set status = 'verified'" in q:
            assert "status <> 'verified'" in q
            for row in self.rows.values():
                if row["id"] == args[0] and row["status"] != "verified":
                    row["status"] = "verified"
                    row["percent_awarded"] = args[1]
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected execute: {q}")


class _Mail:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send(self, **message: Any) -> None:
        if self.fail:
            raise ExternalServiceError("Brevo is down.")
        self.sent.append(message)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, mail: _Mail, user: AuthenticatedUser) -> None:
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_email_client] = lambda: mail
    app.dependency_overrides[get_current_user] = lambda: user


def _resident(**kw: Any) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="general_user", email=ADDRESS, full_name="Juan dela Cruz", **kw
    )


def _token(mail: _Mail) -> str:
    text = mail.sent[-1]["text"]
    link = next(w for w in text.split() if "/verification/email/confirm?token=" in w)
    return parse_qs(urlsplit(link).query)["token"][0]


def _age_sends(db: _Db, user: AuthenticatedUser, by: timedelta) -> None:
    meta = db.rows[user.id]["metadata"]
    meta["sends"] = [(datetime.fromisoformat(s) - by).isoformat() for s in meta["sends"]]


# --------------------------------------------------------------------------- #
# Asking for a link
# --------------------------------------------------------------------------- #
def test_asking_sends_one_link(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)

    r = client.post("/verification/email/request")

    assert r.status_code == 200
    assert r.json() == {
        "message": "Verification email sent. Check your inbox.",
        "email": ADDRESS,
        "sent": True,
        "expires_in_seconds": 86400,
        "resend_after_seconds": 60,
    }
    assert len(mail.sent) == 1
    assert mail.sent[0]["to"] == ADDRESS
    assert "Verify my email" in mail.sent[0]["html"]
    assert _token(mail)
    assert db.rows[user.id]["status"] == "pending"


def test_a_second_ask_inside_the_wait_is_refused(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")

    r = client.post("/verification/email/request")

    assert r.status_code == 429
    assert r.json()["error"] == "email_link_cooldown"
    assert 1 <= r.json()["details"]["retry_after_seconds"] <= 61
    assert len(mail.sent) == 1


def test_after_the_wait_a_new_link_replaces_the_old(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")
    first = _token(mail)
    _age_sends(db, user, timedelta(seconds=61))

    r = client.post("/verification/email/request")

    assert r.status_code == 200
    assert len(mail.sent) == 2
    old = client.get("/verification/email/confirm", params={"token": first})
    assert old.status_code == 400
    assert "This link does not work" in old.text
    new = client.get("/verification/email/confirm", params={"token": _token(mail)})
    assert new.status_code == 200
    assert "Your email is confirmed" in new.text


def test_five_links_a_day(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    for _ in range(5):
        assert client.post("/verification/email/request").status_code == 200
        _age_sends(db, user, timedelta(minutes=2))

    r = client.post("/verification/email/request")

    assert r.status_code == 429
    assert r.json()["error"] == "email_link_daily_limit"
    assert r.json()["details"]["retry_after_seconds"] > 23 * 3600
    assert len(mail.sent) == 5
    # The oldest falls out of the 24 hours, and a link may go again.
    _age_sends(db, user, timedelta(hours=23, minutes=51))
    assert client.post("/verification/email/request").status_code == 200


def test_a_failed_send_records_nothing(client: TestClient) -> None:
    db, user = _Db(), _resident()
    _wire(db, _Mail(fail=True), user)

    r = client.post("/verification/email/request")

    assert r.status_code == 502
    assert db.rows == {}
    mail = _Mail()
    _wire(db, mail, user)
    assert client.post("/verification/email/request").status_code == 200
    assert len(mail.sent) == 1


def test_a_confirmed_address_gets_no_email_and_stays_confirmed(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")
    client.get("/verification/email/confirm", params={"token": _token(mail)})
    _age_sends(db, user, timedelta(minutes=2))

    r = client.post("/verification/email/request")

    assert r.status_code == 200
    assert r.json()["sent"] is False
    assert r.json()["message"] == "Your email is already confirmed."
    assert len(mail.sent) == 1
    assert db.rows[user.id]["status"] == "verified"


def test_an_account_with_no_email_is_refused(client: TestClient) -> None:
    db, mail = _Db(), _Mail()
    _wire(db, mail, AuthenticatedUser(id=uuid4(), role="general_user"))

    r = client.post("/verification/email/request")

    assert r.status_code == 400
    assert mail.sent == []


# --------------------------------------------------------------------------- #
# Opening it
# --------------------------------------------------------------------------- #
def test_the_link_confirms_the_email_on_a_page(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")

    r = client.get("/verification/email/confirm", params={"token": _token(mail)})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert 'name="viewport"' in r.text
    assert "Your email is confirmed" in r.text
    assert "Your trust level is up 10%" in r.text
    assert db.rows[user.id]["status"] == "verified"
    assert db.rows[user.id]["percent_awarded"] == 10


def test_opening_it_again_says_confirmed_and_changes_nothing(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")
    token = _token(mail)
    client.get("/verification/email/confirm", params={"token": token})

    r = client.get("/verification/email/confirm", params={"token": token})

    assert r.status_code == 200
    assert "Your email is confirmed" in r.text
    assert "trust level" not in r.text
    assert db.rows[user.id]["status"] == "verified"


def test_an_expired_link_says_how_to_get_a_new_one(client: TestClient) -> None:
    db, mail, user = _Db(), _Mail(), _resident()
    _wire(db, mail, user)
    client.post("/verification/email/request")
    db.rows[user.id]["metadata"]["expires_at"] = (
        datetime.now(UTC) - timedelta(minutes=1)
    ).isoformat()

    r = client.get("/verification/email/confirm", params={"token": _token(mail)})

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert "This link has expired" in r.text
    assert "Profile, then Verify next to your email" in r.text
    assert db.rows[user.id]["status"] == "pending"


@pytest.mark.parametrize("params", [{"token": "not-a-real-token"}, {}])
def test_an_unknown_link_lands_on_a_page_not_json(
    client: TestClient, params: dict[str, str]
) -> None:
    _wire(_Db(), _Mail(), _resident())

    r = client.get("/verification/email/confirm", params=params)

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert "This link does not work" in r.text
