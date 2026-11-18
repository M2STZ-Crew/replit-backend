"""v1.12.38: fixes from the 18 November 2026 list."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import account_deletion, fire_broadcast

# --------------------------------------------------------------------------- #
# Confirm before use: "an illegitimate email can still sign up (the account
# was created because of the Later button in email verification)".
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _gates(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "require_citizen_email_verification", True)
    monkeypatch.setattr(settings, "require_citizen_phone_verification", False)


def _person(role: str = "general_user", **kw: Any) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, email="maria@example.com", **kw)


class _Db:
    """Answers nothing: the routes here only need to get past the gate."""

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_database] = lambda: _Db()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(person: AuthenticatedUser) -> None:
    app.dependency_overrides[get_current_user] = lambda: person


def test_an_unconfirmed_resident_is_refused_with_its_own_code(client: TestClient) -> None:
    _as(_person(email_verified=False))
    response = client.get("/areas")
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "email_not_verified"
    assert "Confirm your email" in body["message"]


def test_me_says_to_confirm_and_a_new_link_can_be_asked_for(client: TestClient) -> None:
    _as(_person(email_verified=False))
    me = client.get("/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email_verification_required"] is True
    # Asking for a link is never refused by the gate it opens.
    link = client.post("/verification/email/request")
    assert link.json().get("error") != "email_not_verified"


def test_a_confirmed_resident_and_staff_are_let_through(client: TestClient) -> None:
    for person in (
        _person(email_verified=True),
        _person(role="sub_admin", agency_type="bfp", email_verified=False),
    ):
        _as(person)
        assert client.get("/auth/me").json()["email_verification_required"] is False
        answer = client.get("/areas")
        if answer.status_code == 403:
            assert answer.json()["error"] != "email_not_verified"


def test_switched_off_nobody_is_gated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "require_citizen_email_verification", False)
    _as(_person(email_verified=False))
    assert client.get("/auth/me").json()["email_verification_required"] is False


async def test_new_accounts_never_confirmed_go_after_a_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone: list[str] = []
    audited: list[dict[str, Any]] = []
    stale = uuid4()

    class Db:
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            # Residents only, made since the cut-off, a day old, never confirmed.
            assert "general_user" in query
            assert "created_at >= $1" in query
            assert "user_verifications" in query
            assert args[0] == datetime.fromisoformat(get_settings().unconfirmed_purge_since)
            assert args[1] == 24
            return [{"id": stale}]

    class Auth:
        async def admin_delete_user(self, *, user_id: str) -> None:
            gone.append(user_id)

    async def no_photos(storage: Any, paths: Any) -> None:
        return None

    async def audit(db: Any, request: Any, actor: Any, **kw: Any) -> None:
        audited.append(kw)

    monkeypatch.setattr(account_deletion, "remove_photos", no_photos)
    monkeypatch.setattr(account_deletion, "record_audit", audit)
    assert await account_deletion.purge_unconfirmed(Db(), Auth(), object()) == 1
    assert gone == [str(stale)]
    assert audited[0]["metadata"] == {"via": "email_never_confirmed", "hours": 24}


def test_accounts_from_before_the_change_are_kept() -> None:
    """The cut-off is 19 November 2026, Manila: accounts signed up when Later
    was allowed are never deleted for it."""
    since = datetime.fromisoformat(get_settings().unconfirmed_purge_since)
    assert since.isoformat() == "2026-11-19T00:00:00+08:00"


# --------------------------------------------------------------------------- #
# "even outside of 100m everyone get notified (but in the 100m can only
# corroborate)": every resident, once staff verify the fire.
# --------------------------------------------------------------------------- #


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kw: Any) -> Any:
        self.sent.append(kw)
        return SimpleNamespace(invalid_tokens=[])


def _fire_db(residents: list[dict[str, Any]], tokens_each: int = 1) -> Any:
    class Db:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            return {
                "designation": "Taft Avenue",
                "centroid_lat": 14.5378,
                "centroid_lng": 121.0014,
                "created_at": datetime(2026, 11, 18, 9, 30, tzinfo=UTC),
            }

        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            if "from public.users u" in query:
                # Residents only; the fire's reporters and the 100 m
                # corroborators (fresh location, within the radius) are out.
                assert "general_user" in query
                assert "reporter_id" in query
                assert "not (" in query and "ST_DWithin" in query
                assert args[2] == 100
                return residents
            if "device_tokens" in query:
                return [
                    {"fcm_token": f"{uid}-{n}", "app_version": "1.12.49"}
                    for uid in args[0]
                    for n in range(tokens_each)
                ]
            return []

        async def execute(self, query: str, *args: Any) -> str:
            return "OK"

    return Db()


async def test_a_verified_fire_alerts_every_resident_in_their_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox: list[tuple[str, str]] = []

    async def record(db: Any, ids: Any, type_: str, title: str, body: str, data: Any) -> None:
        inbox.append((type_, title))

    monkeypatch.setattr(fire_broadcast, "record_inbox", record)
    push = _Push()
    residents = [
        {"user_id": uuid4(), "language": "tl"},
        {"user_id": uuid4(), "language": "en"},
    ]
    alerted = await fire_broadcast.notify_residents_of_verified_fire(
        _fire_db(residents), uuid4(), push
    )
    assert alerted == 2
    by_title = {s["title"]: s for s in push.sent}
    assert set(by_title) == {"Fire verified", "Kumpirmadong sunog"}
    assert "on Taft Avenue" in by_title["Fire verified"]["body"]
    assert "sa Taft Avenue" in by_title["Kumpirmadong sunog"]["body"]
    for sent in push.sent:
        assert sent["data"]["type"] == "fire_verified"
        assert sent["data"]["designation"] == "Taft Avenue"
        assert sent["data"]["reported_at"].startswith("2026-11-18T09:30")
    assert sorted(inbox) == [
        ("fire_verified", "Fire verified"),
        ("fire_verified", "Kumpirmadong sunog"),
    ]


async def test_a_city_of_phones_goes_in_batches_of_500(monkeypatch: pytest.MonkeyPatch) -> None:
    async def record(*args: Any, **kw: Any) -> None:
        return None

    monkeypatch.setattr(fire_broadcast, "record_inbox", record)
    push = _Push()
    residents = [{"user_id": uuid4(), "language": "en"} for _ in range(400)]
    await fire_broadcast.notify_residents_of_verified_fire(
        _fire_db(residents, tokens_each=3), uuid4(), push
    )
    assert [len(s["tokens"]) for s in push.sent] == [500, 500, 200]


async def test_nobody_to_tell_sends_nothing() -> None:
    push = _Push()
    assert await fire_broadcast.notify_residents_of_verified_fire(_fire_db([]), uuid4(), push) == 0
    assert push.sent == []
