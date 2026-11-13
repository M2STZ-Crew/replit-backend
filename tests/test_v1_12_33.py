"""Backend v1.12.33 (13 Nov 2026): every sound anew, and no phone tone.

- "check all of the sounds and apply it to the new. because we found some
  errors in sound": a phone that had the app before v1.12.23 holds the agency
  alert channels by resource number, and the recordings added since moved the
  numbers. App v1.12.42 makes every sound channel anew, by name
  (SOUND_CHANNELS_V2); a phone is told on them once it registers with that
  version, and on the channels it has until then.
- "custom national id verified sound (id verified and rejected)": the National
  ID review's result plays ID VERIFIED or ID NOT VERIFIED.
- "No phone tone anywhere": a dispatch, an incident routed to a team, BFP's
  answer and the test alert play the person's own sound, and on app v1.12.42 a
  push that names none plays the citizen one.
- "Nearby fire: NEARBY INCIDENT": tests/test_push_alerts.py.
- Barangay 76's fire and medic teams belong to Barangay 76: the tracker shows a
  responder's own agency, not the organisation's.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database, get_push_service
from app.integrations import fcm
from app.integrations.fcm import (
    SOUND_CHANNELS,
    SOUND_CHANNELS_V2,
    UPDATES_CHANNEL,
    PushResult,
    PushService,
    SoundCategory,
    android_config,
    has_new_channels,
    token_versions,
)
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import incident_notify, national_id

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# The channels app v1.12.42 makes
# --------------------------------------------------------------------------- #
def test_every_sound_has_a_channel_of_its_own_anew() -> None:
    assert set(SOUND_CHANNELS_V2) == set(get_args(SoundCategory))
    ids = list(SOUND_CHANNELS_V2.values())
    assert len(set(ids)) == len(ids)
    # None of them is a channel a phone may already hold by number.
    assert not set(ids) & set(SOUND_CHANNELS.values())
    assert SOUND_CHANNELS_V2["id_verified"] == "id_verified_v1"
    assert SOUND_CHANNELS_V2["id_rejected"] == "id_rejected_v1"


@pytest.mark.parametrize("version", ["1.12.42", "1.12.43", "1.13.0", "2.0.0"])
def test_app_1_12_42_and_later_has_them(version: str) -> None:
    assert has_new_channels(version)


@pytest.mark.parametrize("version", ["1.12.41", "1.12.36 (58)", "1.11.99", "", None, "junk"])
def test_an_older_app_or_one_that_never_said_has_not(version: str | None) -> None:
    assert not has_new_channels(version)


@pytest.mark.parametrize("sound", get_args(SoundCategory))
def test_a_new_phone_hears_each_sound_on_its_new_channel(sound: str) -> None:
    note = android_config(sound=sound, modern=True).notification  # type: ignore[arg-type]
    assert note.channel_id == SOUND_CHANNELS_V2[sound]  # type: ignore[index]
    # The file it names, for Android before 8: res/raw/sound_<category>.mp3.
    assert note.sound == f"sound_{sound}"
    assert note.default_sound is False
    assert note.default_vibrate_timings is True


def test_an_older_app_hears_its_own_channels_and_the_id_as_before() -> None:
    assert android_config(sound="medical").notification.channel_id == "alert_medical"
    # No channel for the National ID's sounds before v1.12.42: as before.
    for sound in ("id_verified", "id_rejected"):
        note = android_config(sound=sound).notification  # type: ignore[arg-type]
        assert note.channel_id == UPDATES_CHANNEL
        assert note.default_sound is True


def test_token_versions_reads_device_rows() -> None:
    rows = [
        {"fcm_token": "a", "app_version": "1.12.42"},
        {"fcm_token": "b", "app_version": None},
        {"fcm_token": "c"},
    ]
    assert token_versions(rows) == {"a": "1.12.42", "b": None, "c": None}


# --------------------------------------------------------------------------- #
# One push, each phone on the channels it has
# --------------------------------------------------------------------------- #
class _Sent:
    """Captures what FCM is asked to send; every token succeeds."""

    def __init__(self) -> None:
        self.messages: list[Any] = []

    def __call__(self, message: Any, app: Any = None) -> Any:
        self.messages.append(message)
        ok = type("Response", (), {"success": True, "exception": None})()
        return type(
            "Batch",
            (),
            {
                "success_count": len(message.tokens),
                "failure_count": 0,
                "responses": [ok] * len(message.tokens),
            },
        )()

    def by_channel(self) -> dict[str, tuple[list[str], dict[str, str]]]:
        return {
            m.android.notification.channel_id: (list(m.tokens), dict(m.data)) for m in self.messages
        }


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> _Sent:
    capture = _Sent()
    monkeypatch.setattr(fcm, "_fcm_app", object())
    monkeypatch.setattr(fcm.messaging, "send_each_for_multicast", capture)
    return capture


async def test_a_push_goes_to_each_phone_on_the_channels_it_has(sent: _Sent) -> None:
    result = await PushService().send_to_tokens(
        tokens=["new", "old", "unknown"],
        title="Medical",
        body="An incident asked for a medical team.",
        sound="medical",
        versions={"new": "1.12.42", "old": "1.12.41", "unknown": None},
    )
    assert result.success_count == 3
    assert sent.by_channel() == {
        "alert_medical_v2": (["new"], {"sound_category": "medical"}),
        "alert_medical": (["old", "unknown"], {"sound_category": "medical"}),
    }


async def test_a_push_without_versions_goes_as_to_older_apps(sent: _Sent) -> None:
    await PushService().send_to_tokens(tokens=["a", "b"], title="t", body="b", sound="fire")
    assert list(sent.by_channel()) == ["alert_fire"]


async def test_no_phone_tone_on_a_new_phone(sent: _Sent) -> None:
    # A push that names no sound: the citizen recording on 1.12.42, the
    # general channel (the phone's tone) on an older app, as before.
    await PushService().send_to_tokens(
        tokens=["new", "old"],
        title="t",
        body="b",
        data={"type": "something"},
        versions={"new": "1.12.42", "old": "1.12.40"},
    )
    assert sent.by_channel() == {
        "citizen_nearby_v1": (["new"], {"type": "something", "sound_category": "citizen"}),
        UPDATES_CHANNEL: (["old"], {"type": "something"}),
    }


async def test_a_silent_reminder_stays_silent_and_an_update_keeps_its_channel(
    sent: _Sent,
) -> None:
    await PushService().send_to_tokens(
        tokens=["new"], title="t", body="b", silent=True, versions={"new": "1.12.42"}
    )
    await PushService().send_to_tokens(
        tokens=["new"],
        title="New Update!",
        body="b",
        channel="app_update_en_v1",
        recording="update_en",
        versions={"new": "1.12.42"},
    )
    channels = [m.android.notification.channel_id for m in sent.messages]
    assert channels == ["silent_ping", "app_update_en_v1"]
    assert sent.messages[0].data == {"silent": "true"}
    assert sent.messages[1].android.notification.sound == "update_en"


def test_every_push_says_which_app_each_phone_has() -> None:
    """Every send_to_tokens in the service passes the phones' versions, so a
    new phone is never told on a channel it deleted. "New Update!" names its
    own channel and recording, which both apps have.
    """
    calls: list[tuple[str, str]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.send_to_tokens\(", source):
            depth, end = 0, match.end() - 1
            for end in range(match.end() - 1, len(source)):
                depth += {"(": 1, ")": -1}.get(source[end], 0)
                if depth == 0:
                    break
            calls.append((path.relative_to(ROOT).as_posix(), source[match.end() : end]))
    assert len(calls) >= 10
    for where, arguments in calls:
        if where == "app/workers/app_updates.py":
            assert "channel=channel" in arguments and "recording=recording" in arguments
            continue
        assert "versions=" in arguments, f"{where}: a push without the phones' versions"


# --------------------------------------------------------------------------- #
# The National ID's own sounds
# --------------------------------------------------------------------------- #
class _OneUserDb:
    """One resident with one phone on app 1.12.42."""

    def __init__(self, agency: str | None = None) -> None:
        self.agency = agency

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.device_tokens" in query:
            return [{"user_id": args[0], "fcm_token": "tok", "app_version": "1.12.42"}]
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "agency_type" in query:
            return self.agency
        if "designation" in query:
            return "1.2"
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


@pytest.mark.parametrize(("approved", "sound"), [(True, "id_verified"), (False, "id_rejected")])
async def test_the_national_id_result_plays_its_own_recording(
    monkeypatch: pytest.MonkeyPatch, approved: bool, sound: str
) -> None:
    push = _Push()
    inbox: list[tuple[Any, ...]] = []

    async def record(*args: Any) -> int:
        inbox.append(args)
        return 1

    monkeypatch.setattr(national_id, "PushService", lambda: push)
    monkeypatch.setattr(national_id, "record_inbox", record)
    sent = await national_id.notify_review_decided(
        _OneUserDb(),  # type: ignore[arg-type]
        uuid4(),
        approved=approved,
        notes=None if approved else "The photo is blurred.",
    )
    assert sent == 1
    assert push.sent[0]["sound"] == sound
    assert push.sent[0]["versions"] == {"tok": "1.12.42"}
    assert push.sent[0]["data"] == {"type": "national_id_reviewed"}
    # The inbox row names it too: the iPhone hears its inbox.
    assert inbox[0][-1] == {"type": "national_id_reviewed", "sound_category": sound}


# --------------------------------------------------------------------------- #
# Staff hear their own sound, never the phone's tone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("agency", "sound"), [("medical", "medical"), ("fire_volunteer", "fire")])
async def test_a_dispatched_responder_hears_their_agencys_recording(
    monkeypatch: pytest.MonkeyPatch, agency: str, sound: str
) -> None:
    push = _Push()

    async def no_inbox(*_: Any, **__: Any) -> int:
        return 1

    monkeypatch.setattr(incident_notify, "PushService", lambda: push)
    monkeypatch.setattr(incident_notify, "record_inbox", no_inbox)
    devices = await incident_notify.notify_responder_dispatched(
        _OneUserDb(agency),  # type: ignore[arg-type]
        uuid4(),
        uuid4(),
    )
    assert devices == 1
    assert push.sent[0]["sound"] == sound
    assert push.sent[0]["versions"] == {"tok": "1.12.42"}


class _DeviceDb:
    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.device_tokens" in query:
            return [{"fcm_token": "tok", "app_version": "1.12.42"}]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _ReadyPush(_Push):
    is_available = True


@pytest.mark.parametrize(
    ("role", "agency", "sound"),
    [
        ("general_user", None, "citizen"),
        ("sub_admin", "fire_volunteer", "fire"),
        ("response_team", "medical", "medical"),
        ("sub_admin", "barangay", "barangay"),
    ],
)
def test_the_test_alert_plays_the_persons_own_sound(
    client: TestClient, role: str, agency: str | None, sound: str
) -> None:
    push = _ReadyPush()
    user = AuthenticatedUser(id=uuid4(), role=role, agency_type=agency, phone_verified=True)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: _DeviceDb()
    app.dependency_overrides[get_push_service] = lambda: push
    response = client.post("/devices/test", headers={"Authorization": "Bearer x"})
    assert response.status_code == 200, response.text
    assert push.sent[0]["sound"] == sound
    assert push.sent[0]["versions"] == {"tok": "1.12.42"}


# --------------------------------------------------------------------------- #
# Barangay 76's fire and medic teams on the tracker
# --------------------------------------------------------------------------- #
def test_the_tracker_shows_a_responders_own_agency() -> None:
    source = (ROOT / "app" / "services" / "tracking.py").read_text(encoding="utf-8")
    assert "coalesce(u.agency_type::text, o.agency_type::text) as agency" in source
    assert "coalesce(o.agency_type::text, u.agency_type::text)" not in source
