"""The reporter is told which team verified their fire, never who (hermetic, v1.12.1)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services import incident_notify
from app.services.verifier import VERIFIER_SQL

_AREA = uuid4()
_REPORTER = uuid4()


class _Db:
    def __init__(self, verifier: dict[str, Any] | None) -> None:
        self.verifier = verifier

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        assert query == VERIFIER_SQL
        return self.verifier

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "dt.fcm_token" in query:
            return []  # no phone registered: the inbox row is what we check
        return [{"user_id": _REPORTER}]


@pytest.fixture
def inbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    async def _record(db: Any, users: Any, kind: str, title: str, body: str, data: Any) -> None:
        sent.append((title, body))

    monkeypatch.setattr(incident_notify, "record_inbox", _record)
    return sent


async def test_the_verified_push_names_the_team(inbox: list[tuple[str, str]]) -> None:
    db = _Db({
        "name": "Ramon Dizon", "role": "sub_admin", "verified_at": None,
        "agency": "fire_volunteer", "organization": "Hercules Fire Brigade",
    })
    await incident_notify.notify_incident_reporters(db, _AREA, "incident_verified")  # type: ignore[arg-type]
    title, body = inbox[0]
    assert title == "Report verified"
    assert "verified by Hercules Fire Brigade" in body
    assert "Ramon" not in body


async def test_without_a_verifier_the_push_says_what_it_always_said(
    inbox: list[tuple[str, str]],
) -> None:
    await incident_notify.notify_incident_reporters(_Db(None), _AREA, "incident_verified")  # type: ignore[arg-type]
    assert inbox[0][1] == "Your fire report was verified. Responders are being assigned."
