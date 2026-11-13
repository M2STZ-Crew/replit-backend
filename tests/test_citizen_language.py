"""Residents' alerts in the language they read the app in (hermetic, 5 Nov 2026).

The app is in English or in Tagalog (CEFR B1) and says which with
PUT /auth/me/language. The 150 m neighbourhood alert, news on a report the
resident filed, the National ID answer and the test alert follow it, in the
push and in the inbox (issue list 1.5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.integrations.fcm import PushResult
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import citizen_copy, incident_notify, national_id
from app.workers import neighborhood

AREA = uuid4()


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


# --------------------------------------------------------------------------- #
# The words
# --------------------------------------------------------------------------- #
def test_every_resident_message_is_in_both_languages() -> None:
    tables: list[dict[str, tuple[str, str]]] = [
        citizen_copy.NEIGHBOUR_ALERT,
        citizen_copy.NATIONAL_ID_APPROVED,
        citizen_copy.NATIONAL_ID_RETRY,
        citizen_copy.TEST_ALERT,
        *citizen_copy.REPORTER_MESSAGES.values(),
    ]
    for table in tables:
        assert set(table) == {"en", "tl"}
        assert table["en"] != table["tl"]
        for title, body in table.values():
            assert title.strip() and body.strip()


def test_the_english_table_the_lifecycle_tests_read_is_unchanged() -> None:
    assert incident_notify._REPORTER_MESSAGES["incident_verified"] == (
        "Report verified",
        "Your fire report was verified. Responders are being assigned.",
    )


def test_the_tagalog_neighbour_alert_is_the_prd_alert() -> None:
    assert neighborhood._ALERT_TITLE == "Alerto sa Sunog"
    assert citizen_copy.NEIGHBOUR_ALERT["tl"][0] == "Alerto sa Sunog"


def test_an_unknown_stored_language_reads_as_english() -> None:
    assert citizen_copy.language_of(None) == "en"
    assert citizen_copy.language_of("fil") == "en"
    assert citizen_copy.language_of("tl") == "tl"


# --------------------------------------------------------------------------- #
# PUT /auth/me/language
# --------------------------------------------------------------------------- #
class _Db:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "UPDATE 1"


@pytest.mark.parametrize("language", ["en", "tl"])
def test_the_app_sets_the_language(language: str) -> None:
    db = _Db()
    # Before the phone gate, as the app sends it at sign-in.
    user = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=False)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    try:
        with TestClient(app) as client:
            resp = client.put("/auth/me/language", json={"language": language})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 204
    ((query, args),) = db.executed
    assert "set language = $2" in query
    assert args == (user.id, language)


def test_a_language_the_app_does_not_have_is_refused() -> None:
    user = AuthenticatedUser(id=uuid4(), role="general_user")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = _Db
    try:
        with TestClient(app) as client:
            resp = client.put("/auth/me/language", json={"language": "fr"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# The 150 m alert
# --------------------------------------------------------------------------- #
class _NeighbourDb:
    def __init__(self, users: list[tuple[UUID, str, bool]]) -> None:
        self.users = users

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "alerted_before" in query:
            return [
                {"user_id": u, "language": lang, "alerted_before": seen}
                for u, lang, seen in self.users
            ]
        if "device_tokens" in query:
            return [{"fcm_token": f"tok-{u}"} for u in args[0]]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


async def test_each_neighbour_is_alerted_in_their_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox: list[tuple[list[UUID], str, str]] = []

    async def record(_db: Any, ids: list[UUID], _type: str, title: str, body: str, *_: Any) -> int:
        inbox.append((list(ids), title, body))
        return len(ids)

    monkeypatch.setattr(neighborhood, "record_inbox", record)
    english, tagalog = uuid4(), uuid4()
    push = _Push()
    alerted = await neighborhood.notify_area_neighbors(
        _NeighbourDb([(english, "en", False), (tagalog, "tl", False)]),  # type: ignore[arg-type]
        push,  # type: ignore[arg-type]
        AREA,
        14.5,
        121.0,
    )
    assert alerted == 2
    by_title = {s["title"]: s["tokens"] for s in push.sent}
    assert by_title == {"Fire alert": [f"tok-{english}"], "Alerto sa Sunog": [f"tok-{tagalog}"]}
    # v1.12.33: the nearby-incident recording, the citizen one (it was the
    # staff fire alarm).
    assert {s["sound"] for s in push.sent} == {"citizen"}, "both hear NEARBY INCIDENT"
    assert sorted((ids[0] == english, title) for ids, title, _ in inbox) == [
        (False, "Alerto sa Sunog"),
        (True, "Fire alert"),
    ]


# --------------------------------------------------------------------------- #
# News on a report
# --------------------------------------------------------------------------- #
class _ReporterDb:
    def __init__(self, reporters: list[tuple[UUID, str]]) -> None:
        self.reporters = reporters

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "dt.fcm_token" in query:
            return [{"fcm_token": f"tok-{u}", "language": lang} for u, lang in self.reporters]
        if "r.reporter_id as user_id" in query:
            return [{"user_id": u, "language": lang} for u, lang in self.reporters]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


async def test_reporters_hear_about_their_report_in_their_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox: list[tuple[list[UUID], str]] = []

    async def record(_db: Any, ids: list[UUID], _type: str, title: str, *_: Any) -> int:
        inbox.append((list(ids), title))
        return len(ids)

    push = _Push()
    monkeypatch.setattr(incident_notify, "record_inbox", record)
    monkeypatch.setattr(incident_notify, "PushService", lambda: push)
    english, tagalog = uuid4(), uuid4()
    sent = await incident_notify.notify_incident_reporters(
        _ReporterDb([(english, "en"), (tagalog, "tl")]),  # type: ignore[arg-type]
        AREA,
        "incident_en_route",
    )
    assert sent == 2
    assert {s["title"]: s["tokens"] for s in push.sent} == {
        "Help is on the way": [f"tok-{english}"],
        "Papunta na ang tulong": [f"tok-{tagalog}"],
    }
    assert {s["sound"] for s in push.sent} == {"on_route"}
    assert sorted(title for _, title in inbox) == ["Help is on the way", "Papunta na ang tulong"]


async def test_the_verifying_team_is_named_in_tagalog_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Verifier:
        public_label = "Hercules Fire Brigade"

    async def verifier(*_: Any) -> _Verifier:
        return _Verifier()

    async def record(*_: Any) -> int:
        return 1

    push = _Push()
    monkeypatch.setattr(incident_notify, "fetch_verifier", verifier)
    monkeypatch.setattr(incident_notify, "record_inbox", record)
    monkeypatch.setattr(incident_notify, "PushService", lambda: push)
    await incident_notify.notify_incident_reporters(
        _ReporterDb([(uuid4(), "tl")]),  # type: ignore[arg-type]
        AREA,
        "incident_verified",
    )
    (sent,) = push.sent
    assert sent["body"].startswith("Na-verify ng Hercules Fire Brigade")


# --------------------------------------------------------------------------- #
# The National ID answer
# --------------------------------------------------------------------------- #
async def test_the_national_id_answer_is_in_their_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = uuid4()
    inbox: list[tuple[str, str]] = []

    class _IdDb:
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            if "language from public.users" in query:
                return [{"id": user, "language": "tl"}]
            return []

    async def record(_db: Any, _ids: Any, _type: str, title: str, body: str, *_: Any) -> int:
        inbox.append((title, body))
        return 1

    monkeypatch.setattr(national_id, "record_inbox", record)
    await national_id.notify_review_decided(_IdDb(), user, approved=True)  # type: ignore[arg-type]
    assert inbox == [citizen_copy.NATIONAL_ID_APPROVED["tl"]]
