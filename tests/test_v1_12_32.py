"""Backend v1.12.32 (13 Nov 2026): "New Update!" as soon as a release is out.

"the "new update" push notification doesn't work on my android phone". It was
sent, at the service's next check, 10 minutes apart: app 1.12.40 was published
at 12:16:56, the phone installed it from the update banner by 12:18, and the
12:26 check found it up to date, so it was never told. Now the release workflow
asks for a check as it publishes (POST /app-updates/check), the scheduled check
runs every 2 minutes for when it does not, checks run one at a time, and nobody
told of a version is told of an older one (app/workers/app_updates.py).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_database, get_http_client, get_push_service
from app.core.config import Settings
from app.integrations.fcm import PushResult
from app.main import app
from app.workers import app_updates
from app.workers.app_updates import _DUE_SQL, INBOX_TYPE, LATEST_RELEASE_URL, Checked, check_now


@pytest.fixture(autouse=True)
def _fresh_checks() -> Iterator[None]:
    """Each test starts with no check behind it (and a lock of its own loop)."""
    app_updates._lock = None
    app_updates._last = None
    app_updates._last_asked_at = None
    yield
    app_updates._lock = None
    app_updates._last = None
    app_updates._last_asked_at = None


class _Github:
    """GitHub's latest.json for the newest release, counting the reads."""

    def __init__(self, version: str = "1.12.41") -> None:
        self.version = version
        self.reads: list[str] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._answer))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.reads.append(str(request.url))
        return httpx.Response(200, json={"version": self.version, "build": 63})


class _Db:
    """Answers the due query from what has been written, as the database does:
    a person with an inbox row for the version is not due again. Each call
    yields, as a real query does, so two checks at once would interleave.
    """

    def __init__(self, phones: list[dict[str, Any]]) -> None:
        self.phones = phones
        self.told: set[UUID] = set()
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append((query, args))
        await asyncio.sleep(0.01)
        return [p for p in self.phones if p["user_id"] not in self.told]

    async def execute(self, query: str, *args: Any) -> str:
        await asyncio.sleep(0.01)
        if "public.notifications" in query:
            self.told.update(args[0])
        return "OK"


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


def _phone(version: str, language: str = "en") -> dict[str, Any]:
    user = uuid4()
    return {
        "user_id": user,
        "language": language,
        "fcm_token": f"token-{user}",
        "app_version": version,
    }


# --------------------------------------------------------------------------- #
# The release workflow asks
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _serve(db: _Db, push: _Push, github: _Github) -> None:
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_push_service] = lambda: push
    app.dependency_overrides[get_http_client] = lambda: github.client


def test_the_release_workflow_asks_and_phones_behind_hear_at_once(client: TestClient) -> None:
    behind, current = _phone("1.12.40"), _phone("1.12.41")
    db, push, github = _Db([behind, current]), _Push(), _Github("1.12.41")
    _serve(db, push, github)

    # No account: the workflow has none, and needs none.
    response = client.post("/app-updates/check")
    assert response.status_code == 200
    # What it found, for the workflow to compare with what it published;
    # how many were told stays in the log.
    assert response.json() == {"version": "1.12.41"}

    assert github.reads == [LATEST_RELEASE_URL]
    assert [p["tokens"] for p in push.sent] == [[behind["fcm_token"]]]
    sent = push.sent[0]
    # With its recording, in the reader's language (v1.12.30).
    assert sent["channel"] == "app_update_en_v1"
    assert sent["recording"] == "update_en"
    assert sent["title"] == "New Update!"
    assert sent["data"] == {"type": INBOX_TYPE, "version": "1.12.41"}


def test_the_ask_takes_nothing_from_the_caller(client: TestClient) -> None:
    db, push, github = _Db([_phone("1.12.40")]), _Push(), _Github("1.12.41")
    _serve(db, push, github)
    response = client.post("/app-updates/check?version=9.9.9", json={"version": "9.9.9"})
    assert response.json() == {"version": "1.12.41"}
    assert {p["data"]["version"] for p in push.sent} == {"1.12.41"}


def test_a_release_that_cannot_be_read_answers_none(client: TestClient) -> None:
    db, push = _Db([_phone("1.12.40")]), _Push()
    github = _Github()
    github.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    _serve(db, push, github)
    response = client.post("/app-updates/check")
    assert response.status_code == 200
    assert response.json() == {"version": None}
    assert push.sent == []


# --------------------------------------------------------------------------- #
# One check at a time, and a burst of asks reads GitHub once
# --------------------------------------------------------------------------- #
async def test_two_checks_at_once_tell_each_person_once() -> None:
    phones = [_phone("1.12.40"), _phone("1.12.39", "tl")]
    db, push, github = _Db(phones), _Push(), _Github("1.12.41")
    # The workflow's ask and the scheduled check, together.
    first, second = await asyncio.gather(
        check_now(db, push, github.client, asked=True),  # type: ignore[arg-type]
        check_now(db, push, github.client),  # type: ignore[arg-type]
    )
    assert sorted([first.told, second.told]) == [0, 2]
    told = sorted(token for p in push.sent for token in p["tokens"])
    assert told == sorted(p["fcm_token"] for p in phones)


async def test_a_burst_of_asks_reads_github_once() -> None:
    db, push, github = _Db([_phone("1.12.40")]), _Push(), _Github("1.12.41")
    answers = [
        await check_now(db, push, github.client, asked=True)  # type: ignore[arg-type]
        for _ in range(3)
    ]
    assert len(github.reads) == 1
    assert answers[0] == Checked(version="1.12.41", told=1)
    assert all(a.version == "1.12.41" for a in answers)
    assert len(push.sent) == 1
    # The scheduled check always reads.
    await check_now(db, push, github.client)  # type: ignore[arg-type]
    assert len(github.reads) == 2


async def test_an_ask_after_the_cooldown_reads_again(monkeypatch: pytest.MonkeyPatch) -> None:
    db, push, github = _Db([]), _Push(), _Github("1.12.41")
    clock = iter([100.0, 100.0 + app_updates.ASK_COOLDOWN_SECONDS + 1])
    monkeypatch.setattr(app_updates, "_clock", lambda: next(clock))
    await check_now(db, push, github.client, asked=True)  # type: ignore[arg-type]
    await check_now(db, push, github.client, asked=True)  # type: ignore[arg-type]
    assert len(github.reads) == 2


async def test_a_failed_announcement_does_not_stop_the_checks() -> None:
    class _Down(_Db):
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            raise ConnectionError("database away")

    github = _Github("1.12.41")
    checked = await check_now(_Down([]), _Push(), github.client)  # type: ignore[arg-type]
    assert checked == Checked(version="1.12.41", told=0)


# --------------------------------------------------------------------------- #
# Never an older version after a newer one
# --------------------------------------------------------------------------- #
def test_nobody_told_of_a_version_or_a_newer_one_is_due() -> None:
    query = " ".join(_DUE_SQL.split())
    # Compared as numbers, not text: {1,12,9} < {1,12,10}.
    assert ">= string_to_array($1, '.')::int[]" in query
    assert "string_to_array(n.data ->> 'version', '.')::int[]" in query
    # A row whose version is not one is passed over, not cast.
    assert "case when n.data ->> 'version' ~ '^[0-9]+[.][0-9]+[.][0-9]+$'" in query
    assert "n.data ->> 'version' = $1" not in query
    # Still Android phones only, still each person's own rows.
    assert "d.platform = 'android'" in query
    assert "n.user_id = d.user_id and n.type = 'app_update'" in query


async def test_the_query_is_asked_with_the_release_read() -> None:
    db, push, github = _Db([]), _Push(), _Github("1.12.41")
    await check_now(db, push, github.client)  # type: ignore[arg-type]
    assert db.queries == [(_DUE_SQL, ("1.12.41",))]


# --------------------------------------------------------------------------- #
# The scheduled check
# --------------------------------------------------------------------------- #
def test_the_scheduled_check_runs_every_2_minutes() -> None:
    assert Settings.model_fields["app_update_check_minutes"].default == 2


def test_the_scheduled_check_goes_through_the_same_door() -> None:
    tick = inspect.getsource(app_updates.app_updates_tick)
    assert "await check_now(database, PushService(), client)" in tick
    assert "announce(" not in tick


def test_each_send_is_logged() -> None:
    source = inspect.getsource(app_updates.announce)
    assert '"app_update_sent"' in source
    assert "sent=result.success_count" in source
    assert "failed=result.failure_count" in source
