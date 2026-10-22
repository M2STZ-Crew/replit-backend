"""Pushes that reach people outside the app, and ring for a fire (hermetic, v1.12.6).

What these pin:
- each sound has its own channel and recording; a silent push only vibrates;
  anything without a sound is an update with the phone's tone (v1.12.9);
- staff hear about a new fire: every active responder and coordinator whose
  agency can see it, each with their own agency's sound — the first report
  only, not each one that joins it — and coordinators start a reminder cycle;
- a neighbour's first alert plays the fire sound, the reminders the citizen one;
- when FCM will not start, the server says why in words that never quote the
  credentials.

Nothing here talks to Firebase.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import reports
from app.integrations import fcm
from app.integrations.fcm import (
    PushResult,
    _CredentialsError,
    _service_account,
    android_config,
    sound_for_agency,
)
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
# The channels
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("sound", "channel"),
    [
        ("fire", "alert_fire"),
        ("police", "alert_police"),
        ("medical", "alert_medical"),
        ("barangay", "alert_barangay"),
    ],
)
def test_an_alert_plays_its_recording_on_its_own_channel(sound: Any, channel: str) -> None:
    note = android_config(sound=sound, tag="incident-1").notification
    assert note is not None
    assert note.channel_id == channel
    assert note.sound == f"sound_{sound}"
    assert note.default_sound is False
    assert note.priority == "max"
    assert note.visibility == "public"
    assert note.tag == "incident-1"


def test_a_residents_update_plays_the_citizen_recording() -> None:
    note = android_config(sound="citizen").notification
    assert note is not None
    assert note.channel_id == "citizen_updates"
    assert note.sound == "sound_citizen"
    assert note.priority == "high", "news, not an emergency"


def test_a_silent_ping_only_vibrates() -> None:
    note = android_config(silent=True).notification
    assert note is not None
    assert note.channel_id == "silent_ping"
    assert note.sound is None and note.default_sound is False
    assert note.default_vibrate_timings is True


def test_anything_else_is_an_update_with_the_phones_tone() -> None:
    config = android_config()
    note = config.notification
    assert note is not None
    assert note.channel_id == "updates"
    assert note.sound is None
    assert note.default_sound is True
    assert config.priority == "high", "delivered at once either way"


@pytest.mark.parametrize(
    ("agency", "sound"),
    [
        ("fire_volunteer", "fire"),
        ("bfp", "fire"),
        ("police", "police"),
        ("medical", "medical"),
        ("barangay", "barangay"),
        (None, "fire"),
    ],
)
def test_staff_hear_their_own_agencys_sound(agency: str | None, sound: str) -> None:
    assert sound_for_agency(agency) == sound


async def test_the_data_says_which_sound_for_the_open_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    def send(message: Any, app: Any) -> Any:
        sent.append(message)
        return SimpleNamespace(success_count=1, failure_count=0, responses=[])

    monkeypatch.setattr(fcm, "_fcm_app", object())
    monkeypatch.setattr(fcm.messaging, "send_each_for_multicast", send)
    service = fcm.PushService()
    await service.send_to_tokens(tokens=["t"], title="x", body="y", data={"a": "1"}, sound="police")
    await service.send_to_tokens(tokens=["t"], title="x", body="y", silent=True)
    await service.send_to_tokens(tokens=["t"], title="x", body="y")
    assert sent[0].data == {"a": "1", "sound_category": "police"}
    assert sent[1].data == {"silent": "true"}
    assert sent[2].data == {}


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
    """Staff as (id, role, agency); each has one phone, token ``tok-<n>``."""

    def __init__(
        self, *, asked: list[str], staff: list[tuple[UUID, str, str]], phones: bool = True
    ) -> None:
        self.asked = asked
        self.staff = staff
        self.phones = phones
        self.staff_query: tuple[str, tuple[Any, ...]] | None = None
        self.pings: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return {"designation": "Area 12", "asked": self.asked}

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.users u" in query:
            self.staff_query = (query, args)
            return [{"id": i, "role": r, "agency_type": a} for i, r, a in self.staff]
        if "device_tokens" in query and self.phones:
            return [
                {"user_id": i, "fcm_token": f"tok-{n}"} for n, (i, _, _) in enumerate(self.staff)
            ]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        if "coordinator_pings" in query:
            self.pings.append(args)
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


async def test_a_new_fire_alerts_staff_each_with_their_agencys_sound(
    push: _Push, inbox: list[tuple[Any, ...]]
) -> None:
    captain, firefighter, medic = uuid4(), uuid4(), uuid4()
    db = _NotifyDb(
        asked=["fire_volunteer", "medical"],
        staff=[
            (captain, "sub_admin", "fire_volunteer"),
            (firefighter, "response_team", "bfp"),
            (medic, "response_team", "medical"),
        ],
    )

    assert await notify_staff_new_incident(db, AREA) == 3  # type: ignore[arg-type]

    query, args = db.staff_query  # type: ignore[misc]
    assert "role in ('sub_admin', 'response_team')" in query
    assert "u.is_active" in query, "a deactivated account hears nothing"
    assert args == (["fire_volunteer", "bfp", "medical"],)

    [(users, kind, title, body, data)] = inbox
    assert users == [captain, firefighter, medic] and kind == "incident_new"
    assert title == "Fire reported: Area 12"
    assert data == {"area_id": str(AREA), "event": "incident_new"}

    by_sound = {s["sound"]: s["tokens"] for s in push.sent}
    assert by_sound == {"fire": ["tok-0", "tok-1"], "medical": ["tok-2"]}
    for sent in push.sent:
        assert sent["data"] == {
            "type": "incident_new",
            "area_id": str(AREA),
            "event": "incident_new",
        }
        assert sent["tag"] == f"incident-{AREA}"

    [(area, coordinators)] = db.pings
    assert area == AREA and coordinators == [captain], "only coordinators are reminded"


async def test_no_staff_no_push(push: _Push, inbox: list[tuple[Any, ...]]) -> None:
    db = _NotifyDb(asked=["fire_volunteer"], staff=[])
    assert await notify_staff_new_incident(db, AREA) == 0  # type: ignore[arg-type]
    assert push.sent == [] and inbox == [] and db.pings == []


async def test_staff_without_a_phone_still_get_the_inbox_row(
    push: _Push, inbox: list[tuple[Any, ...]]
) -> None:
    db = _NotifyDb(asked=["bfp"], staff=[(uuid4(), "sub_admin", "bfp")], phones=False)
    assert await notify_staff_new_incident(db, AREA) == 1  # type: ignore[arg-type]
    assert len(inbox) == 1 and push.sent == []
    assert len(db.pings) == 1, "the cycle starts; it reaches a phone once one is registered"


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


async def test_a_neighbours_first_alert_plays_fire_and_the_reminders_citizen(
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
    by_sound = {s["sound"]: s["tokens"] for s in push.sent}
    assert by_sound == {"fire": [f"tok-{new}"], "citizen": [f"tok-{seen}"]}
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


def test_real_line_breaks_in_the_private_key_are_accepted() -> None:
    # A dashboard that turned the key's \n escapes into real line breaks.
    broken = json.dumps(_KEY).replace("\\n", "\n")
    assert "\n" in broken
    key = str(_service_account(broken)["private_key"])
    assert key.startswith("-----BEGIN PRIVATE KEY-----\n")


def test_a_base64_encoded_key_is_decoded() -> None:
    encoded = base64.b64encode(json.dumps(_KEY).encode()).decode()
    assert _service_account(encoded)["project_id"] == "replit-test"


@pytest.mark.parametrize(
    ("value", "where"),
    [
        (json.dumps(_KEY)[:60], "stops before the closing }"),
        ('{"type": "service_account", SECRETSECRET}', "line 1, column"),
    ],
)
def test_a_broken_paste_says_where_without_quoting_it(value: str, where: str) -> None:
    with pytest.raises(_CredentialsError) as caught:
        _service_account(value)
    assert where in str(caught.value)
    assert "SECRETSECRET" not in str(caught.value)
    assert "/etc/secrets/" in str(caught.value), "the Secret File way out"


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
