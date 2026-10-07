"""Pushes that reach people outside the app, and ring for a fire (hermetic, v1.12.6).

What these pin:
- a push that says there is a fire goes to the app's fire channel with the
  fire alarm; everything else to the updates channel with the phone's tone;
- staff hear about a new fire: every active responder and coordinator whose
  agency can see it — the first report only, not each one that joins it;
- a neighbour's first alert rings the alarm, the reminders after it do not;
- when FCM will not start, the server says why in words that never quote the
  credentials.

Nothing here talks to Firebase.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import reports
from app.integrations import fcm
from app.integrations.fcm import PushResult, _CredentialsError, _service_account, android_config
from app.main import app
from app.services import incident_notify
from app.services.incident_notify import notify_staff_new_incident, staff_agencies_for
from app.workers import neighborhood
from tests.test_report_in_progress import _Db as _SubmitDb
from tests.test_report_in_progress import _Storage, _submit, _wire

AREA = uuid4()


class _Push:
    """Records each send: who, and whether it rang the alarm."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


# --------------------------------------------------------------------------- #
# The two channels
# --------------------------------------------------------------------------- #
def test_a_fire_rings_the_fire_alarm_channel() -> None:
    note = android_config(alert=True, tag="incident-1").notification
    assert note is not None
    assert note.channel_id == "fire_alerts"
    assert note.sound == "fire_alarm"
    assert note.default_sound is False
    assert note.priority == "max"
    assert note.visibility == "public"
    assert note.tag == "incident-1"


def test_anything_else_is_an_update_with_the_phones_tone() -> None:
    config = android_config(alert=False)
    note = config.notification
    assert note is not None
    assert note.channel_id == "updates"
    assert note.sound is None
    assert note.default_sound is True
    assert config.priority == "high", "delivered at once either way"


# --------------------------------------------------------------------------- #
# Who hears about a new fire
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("asked", "reached"),
    [
        (["fire_volunteer"], ["fire_volunteer", "bfp"]),
        (["bfp"], ["fire_volunteer", "bfp"]),
        (["fire_volunteer", "medical"], ["fire_volunteer", "bfp", "medical"]),
        (["police"], ["police"]),
        (["barangay", "police"], ["police", "barangay"]),
        ([], []),
    ],
)
def test_staff_hear_about_the_fires_they_can_see(asked: list[str], reached: list[str]) -> None:
    assert staff_agencies_for(asked) == reached


class _NotifyDb:
    def __init__(self, *, asked: list[str], staff: list[UUID], tokens: list[str]) -> None:
        self.asked = asked
        self.staff = staff
        self.tokens = tokens
        self.staff_query: tuple[str, tuple[Any, ...]] | None = None
        self.inbox: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return {"designation": "Area 12", "asked": self.asked}

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.users u" in query:
            self.staff_query = (query, args)
            return [{"id": s} for s in self.staff]
        if "device_tokens" in query:
            return [{"fcm_token": t} for t in self.tokens]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        if "notifications" in query:
            self.inbox.append(args)
        return "OK"


@pytest.fixture
def push(monkeypatch: pytest.MonkeyPatch) -> _Push:
    recorder = _Push()
    monkeypatch.setattr(incident_notify, "PushService", lambda: recorder)
    return recorder


@pytest.fixture
def inbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []

    async def record(db: Any, user_ids: list[UUID], kind: str, *rest: Any) -> None:
        rows.append((list(user_ids), kind, *rest))

    monkeypatch.setattr(incident_notify, "record_inbox", record)
    return rows


async def test_a_new_fire_alerts_staff_with_the_alarm(
    push: _Push, inbox: list[tuple[Any, ...]]
) -> None:
    staff = [uuid4(), uuid4()]
    db = _NotifyDb(asked=["fire_volunteer"], staff=staff, tokens=["t1", "t2"])

    assert await notify_staff_new_incident(db, AREA) == 2  # type: ignore[arg-type]

    query, args = db.staff_query  # type: ignore[misc]
    assert "role in ('sub_admin', 'response_team')" in query
    assert "u.is_active" in query, "a deactivated account hears nothing"
    assert args == (["fire_volunteer", "bfp"],)

    [(users, kind, title, body, data)] = inbox
    assert users == staff and kind == "incident_new"
    assert title == "Fire reported: Area 12"
    assert data == {"area_id": str(AREA), "event": "incident_new"}

    [sent] = push.sent
    assert sent["tokens"] == ["t1", "t2"]
    assert sent["alert"] is True
    assert sent["data"] == {"type": "incident_new", "area_id": str(AREA), "event": "incident_new"}
    assert sent["tag"] == f"incident-{AREA}"


async def test_no_staff_no_push(push: _Push, inbox: list[tuple[Any, ...]]) -> None:
    db = _NotifyDb(asked=["fire_volunteer"], staff=[], tokens=["t1"])
    assert await notify_staff_new_incident(db, AREA) == 0  # type: ignore[arg-type]
    assert push.sent == [] and inbox == []


async def test_staff_without_a_phone_still_get_the_inbox_row(
    push: _Push, inbox: list[tuple[Any, ...]]
) -> None:
    db = _NotifyDb(asked=["bfp"], staff=[uuid4()], tokens=[])
    assert await notify_staff_new_incident(db, AREA) == 1  # type: ignore[arg-type]
    assert len(inbox) == 1 and push.sent == []


# --------------------------------------------------------------------------- #
# Only the first report of a fire alerts staff
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _JoinedDb(_SubmitDb):
    """A report that joins a fire already known: the area has two now."""

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        row = await super().fetchrow(query, *args)
        if row is not None and "report_count" in row:
            row = {**row, "report_count": 2}
        return row


@pytest.mark.parametrize(("db_class", "alerted"), [(_SubmitDb, True), (_JoinedDb, False)])
def test_only_the_report_that_makes_the_incident_alerts_staff(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_class: type, alerted: bool
) -> None:
    _wire(db_class(None), _Storage(), monkeypatch)
    called: list[UUID] = []

    async def record(db: Any, area_id: UUID) -> int:
        called.append(area_id)
        return 1

    monkeypatch.setattr(reports, "notify_staff_new_incident", record)
    assert _submit(client).status_code == 201
    assert bool(called) is alerted


def test_a_failed_staff_alert_does_not_fail_the_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(_SubmitDb(None), _Storage(), monkeypatch)

    async def broken(*_: Any) -> int:
        raise RuntimeError("FCM down")

    monkeypatch.setattr(reports, "notify_staff_new_incident", broken)
    assert _submit(client).status_code == 201


# --------------------------------------------------------------------------- #
# Neighbours: the alarm once, then reminders
# --------------------------------------------------------------------------- #
class _NeighbourDb:
    def __init__(self, users: list[tuple[UUID, bool]]) -> None:
        self.users = users

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "alerted_before" in query:
            return [{"user_id": u, "alerted_before": seen} for u, seen in self.users]
        if "device_tokens" in query:
            return [{"fcm_token": f"tok-{u}"} for u in args[0]]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


async def test_a_neighbours_first_alert_rings_and_the_reminders_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_inbox(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(neighborhood, "record_inbox", no_inbox)
    new, seen = uuid4(), uuid4()
    push = _Push()

    alerted = await neighborhood.notify_area_neighbors(
        _NeighbourDb([(new, False), (seen, True)]),  # type: ignore[arg-type]
        push,  # type: ignore[arg-type]
        AREA,
        14.5,
        121.0,
    )

    assert alerted == 2
    by_alarm = {s["alert"]: s["tokens"] for s in push.sent}
    assert by_alarm == {True: [f"tok-{new}"], False: [f"tok-{seen}"]}
    assert {s["tag"] for s in push.sent} == {f"nearby-{AREA}"}, "reminders replace"
    assert {s["data"]["type"] for s in push.sent} == {"neighborhood_alert"}


# --------------------------------------------------------------------------- #
# Why FCM would not start, said safely
# --------------------------------------------------------------------------- #
_KEY = {
    "type": "service_account",
    "project_id": "replit-test",
    "private_key": "-----BEGIN PRIVATE KEY-----\nSECRETSECRET\n-----END PRIVATE KEY-----\n",
    "client_email": "x@replit-test.iam.gserviceaccount.com",
}


def test_a_pasted_key_survives_quotes_around_it() -> None:
    # As copied from a .env line: FCM_CREDENTIALS_JSON='{...}'
    assert _service_account(f"'{json.dumps(_KEY)}'")["project_id"] == "replit-test"
    assert _service_account(f"  {json.dumps(_KEY)}\n")["project_id"] == "replit-test"


def test_doubled_backslashes_in_the_private_key_are_undone() -> None:
    doubled = json.dumps(_KEY).replace("\\n", "\\\\n")
    assert "\n" in str(_service_account(doubled)["private_key"])


def test_a_key_that_is_not_json_says_so_without_quoting_it() -> None:
    with pytest.raises(_CredentialsError) as caught:
        _service_account("SECRETSECRET not json")
    assert "not valid JSON" in str(caught.value)
    assert "SECRETSECRET" not in str(caught.value)


def test_json_that_is_not_a_service_account_says_so() -> None:
    with pytest.raises(_CredentialsError) as caught:
        _service_account(json.dumps({"type": "authorized_user"}))
    assert "not a Firebase service-account key" in str(caught.value)


def _settings(**values: str) -> SimpleNamespace:
    json_ = values.get("json", "")
    file_ = values.get("file", "")
    return SimpleNamespace(
        fcm_credentials_json=json_,
        fcm_credentials_file=file_,
        fcm_configured=bool(json_ or file_),
    )


@pytest.mark.parametrize(
    ("settings", "phrase"),
    [
        (_settings(file="laptop-only.json"), "set FCM_CREDENTIALS_JSON"),
        (_settings(json="SECRETSECRET"), "not valid JSON"),
        (_settings(json=json.dumps(_KEY)), "was refused"),
    ],
)
def test_readiness_says_what_to_fix(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    settings: SimpleNamespace,
    phrase: str,
) -> None:
    # Set through monkeypatch first so whatever init_fcm writes is put back.
    monkeypatch.setattr(fcm, "_fcm_app", None)
    monkeypatch.setattr(fcm, "_fcm_state", "unconfigured")
    monkeypatch.setattr(fcm, "_fcm_reason", None)
    monkeypatch.setattr(fcm, "get_settings", lambda: settings)
    fcm.init_fcm()
    checks = client.get("/health/ready").json()["checks"]
    assert checks["push"] == "failed"
    assert phrase in checks["push_detail"]
    assert "SECRETSECRET" not in json.dumps(checks)


def test_a_working_push_has_no_detail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fcm, "_fcm_state", "ready")
    monkeypatch.setattr(fcm, "_fcm_reason", None)
    checks = client.get("/health/ready").json()["checks"]
    assert checks["push"] == "ok" and "push_detail" not in checks
