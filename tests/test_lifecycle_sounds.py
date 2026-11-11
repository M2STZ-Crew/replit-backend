"""What a resident hears as their report moves on (hermetic, v1.12.19).

The mapping the 2 November brief asked for, pinned where the server decides it:

    Reported   -> nothing
    Verified   -> "Report acknowledged" (sound_verified, citizen_verified_v3)
    On the way -> "On route"            (sound_on_route, citizen_on_route_v2)
    On scene   -> "On scene"            (sound_on_scene, citizen_on_scene_v2)
    Fire out   -> "Fire out"            (sound_fire_out, citizen_fire_out_v2)
    Rejected   -> "Rejected"            (sound_rejected, citizen_rejected_v2)

9 November: rejected has its own recording (it played the general one), and
verified moved to a v2 channel, since sound_rejected renumbers sound_verified
for a channel made before app v1.12.23.

One push per status change, so one sound: a second verifier, a second
responder or a second Arrived press changes no status and sends no stage
sound. The channel ids must match the ones the app makes
(android/app/src/main/kotlin/.../MainActivity.kt in replit-android); a channel
the phone does not have plays the phone's default tone instead.

Nothing here talks to Firebase.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.integrations.fcm import SOUND_CHANNELS, PushResult, android_config
from app.services import incident_notify
from app.services.incident_notify import (
    _REPORTER_MESSAGES,
    _REPORTER_SOUNDS,
    notify_incident_reporters,
)

AREA = uuid4()

_STAGES = {
    "incident_verified": ("verified", "citizen_verified_v3"),
    "incident_en_route": ("on_route", "citizen_on_route_v2"),
    "incident_arrived": ("on_scene", "citizen_on_scene_v2"),
    "incident_resolved": ("fire_out", "citizen_fire_out_v2"),
    "incident_rejected": ("rejected", "citizen_rejected_v2"),
}


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


class _Db:
    """One reporter with one phone."""

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "dt.fcm_token" in query:
            return [{"fcm_token": "tok-reporter"}]
        return [{"user_id": uuid4()}]

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@pytest.fixture
def push(monkeypatch: pytest.MonkeyPatch) -> _Push:
    recorder = _Push()
    monkeypatch.setattr(incident_notify, "PushService", lambda: recorder)

    async def no_inbox(*args: Any) -> None:
        return None

    async def no_verifier(*args: Any) -> None:
        return None

    monkeypatch.setattr(incident_notify, "record_inbox", no_inbox)
    monkeypatch.setattr(incident_notify, "fetch_verifier", no_verifier)
    return recorder


def test_each_stage_has_its_own_sound_and_channel() -> None:
    assert {e: s for e, (s, _) in _STAGES.items()} == _REPORTER_SOUNDS
    for sound, channel in _STAGES.values():
        assert SOUND_CHANNELS[sound] == channel
        note = android_config(sound=sound).notification
        assert note.channel_id == channel
        assert note.sound == f"sound_{sound}"
        assert note.default_sound is False
    assert len({channel for _, channel in _STAGES.values()}) == len(_STAGES)


def test_reported_has_no_stage_sound() -> None:
    # Filing a report sends the reporter nothing: the neighbour alert leaves
    # out the area's reporters, and the new-fire alert goes to staff only. The
    # reporter hears only these: the stages, rejected among them, and one
    # piece of news.
    assert set(_REPORTER_MESSAGES) == {*_STAGES, "responder_dispatched"}


@pytest.mark.parametrize(("event", "expected"), list(_STAGES.items()))
async def test_a_stage_sends_one_push_with_its_sound(
    push: _Push, event: str, expected: tuple[str, str]
) -> None:
    assert await notify_incident_reporters(_Db(), AREA, event) == 1  # type: ignore[arg-type]

    [sent] = push.sent
    assert sent["tokens"] == ["tok-reporter"]
    assert sent["sound"] == expected[0]
    assert sent["data"]["event"] == event
    assert sent["tag"] == f"report-{AREA}", "a later stage replaces it in the shade"


@pytest.mark.parametrize(
    "event",
    # A later verifier, the incident's own arrival in the feed, a report filed
    # or closed afterwards: none of them is a stage, so none sends a stage sound.
    ["incident_accepted", "incident_new", "post_incident_report_added", "incident_closed"],
)
async def test_what_is_not_a_stage_sends_the_reporter_nothing(push: _Push, event: str) -> None:
    assert await notify_incident_reporters(_Db(), AREA, event) == 0  # type: ignore[arg-type]
    assert push.sent == []


@pytest.mark.parametrize("event", ["responder_dispatched"])
async def test_other_news_keeps_the_report_updates_sound(push: _Push, event: str) -> None:
    # A second truck on its way: news, not a stage, so the general "Report
    # updates" recording, never a stage's.
    await notify_incident_reporters(_Db(), AREA, event)  # type: ignore[arg-type]
    [sent] = push.sent
    assert sent["sound"] == "citizen"
    assert sent["sound"] not in {s for s, _ in _STAGES.values()}
