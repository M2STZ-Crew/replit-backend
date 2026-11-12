"""Backend v1.12.30 (12 Nov 2026): "New Update!" in its own voice.

"update notification sound is in my downloads (replit tutorial). so put it"
(answered: by language, and it still vibrates). A phone with app v1.12.38 or
later is told on its reader's language's channel, which plays the update's
recording; an older phone, which has neither, is told as in v1.12.29, with
its own tone (app/workers/app_updates.py, app/integrations/fcm.py).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.integrations.fcm import (
    APP_UPDATE_RECORDINGS,
    APP_UPDATES_CHANNEL,
    PushResult,
    android_config,
)
from app.workers.app_updates import (
    INBOX_TYPE,
    announce,
    has_recordings,
    update_channel,
)


# --------------------------------------------------------------------------- #
# Which phones have the recordings
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("version", ["1.12.38", "1.12.39", "1.13.0", "2.0.0"])
def test_app_1_12_38_and_later_has_them(version: str) -> None:
    assert has_recordings(version)


@pytest.mark.parametrize("version", ["1.12.37", "1.12.36 (58)", "1.11.99", "", None, "junk"])
def test_an_older_app_or_one_that_never_said_has_not(version: str | None) -> None:
    assert not has_recordings(version)


def test_each_language_has_its_channel_and_recording() -> None:
    # The ids and files app v1.12.38 makes (MainActivity.kt, res/raw).
    assert APP_UPDATE_RECORDINGS == {
        "en": ("app_update_en_v1", "update_en"),
        "tl": ("app_update_tl_v1", "update_tl"),
    }
    assert update_channel("en", True) == ("app_update_en_v1", "update_en")
    assert update_channel("tl", True) == ("app_update_tl_v1", "update_tl")
    # An older app: the channel it has, and the phone's tone.
    assert update_channel("en", False) == (APP_UPDATES_CHANNEL, None)
    assert update_channel("tl", False) == (APP_UPDATES_CHANNEL, None)


def test_android_plays_the_recording_on_its_channel_and_vibrates() -> None:
    config = android_config(channel="app_update_tl_v1", recording="update_tl")
    assert config.notification.channel_id == "app_update_tl_v1"
    # Android before 8 plays the file the push names; later, the channel's.
    assert config.notification.sound == "update_tl"
    assert config.notification.default_sound is False
    assert config.notification.default_vibrate_timings is True
    # Without a recording it is still the phone's tone (v1.12.29).
    tone = android_config(channel=APP_UPDATES_CHANNEL)
    assert tone.notification.sound is None
    assert tone.notification.default_sound is True


# --------------------------------------------------------------------------- #
# Telling them
# --------------------------------------------------------------------------- #
class _Db:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(("fetch", (query, *args)))
        return self.rows

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(("execute", (query, *args)))
        return "OK"


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


def _phone(user: UUID, version: str | None, language: str = "en") -> dict[str, Any]:
    return {
        "user_id": user,
        "language": language,
        "fcm_token": f"token-{user}-{version}",
        "app_version": version,
    }


async def test_each_phone_hears_what_it_can_play_in_its_readers_language() -> None:
    english_new, english_old, tagalog_new, tagalog_old = uuid4(), uuid4(), uuid4(), uuid4()
    db = _Db(
        [
            _phone(english_new, "1.12.38"),
            _phone(english_old, "1.12.36 (58)"),
            _phone(tagalog_new, "1.12.38", "tl"),
            _phone(tagalog_old, "1.12.37", "tl"),
        ]
    )
    push = _Push()
    assert await announce(db, push, "1.12.39") == 4  # type: ignore[arg-type]

    by_channel = {p["channel"]: p for p in push.sent if p["channel"] != APP_UPDATES_CHANNEL}
    assert by_channel["app_update_en_v1"]["tokens"] == [f"token-{english_new}-1.12.38"]
    assert by_channel["app_update_en_v1"]["recording"] == "update_en"
    assert by_channel["app_update_en_v1"]["title"] == "New Update!"
    assert by_channel["app_update_tl_v1"]["tokens"] == [f"token-{tagalog_new}-1.12.38"]
    assert by_channel["app_update_tl_v1"]["recording"] == "update_tl"
    assert by_channel["app_update_tl_v1"]["title"] == "May Bagong Update!"

    tone = [p for p in push.sent if p["channel"] == APP_UPDATES_CHANNEL]
    assert {tuple(p["tokens"]) for p in tone} == {
        (f"token-{english_old}-1.12.36 (58)",),
        (f"token-{tagalog_old}-1.12.37",),
    }
    for sent in tone:
        assert sent["recording"] is None
    for sent in push.sent:
        # Still a push of its own kind, vibrating, that a newer one replaces.
        assert sent.get("sound") is None and not sent.get("silent")
        assert sent["data"] == {"type": INBOX_TYPE, "version": "1.12.39"}
        assert sent["tag"] == INBOX_TYPE


async def test_one_person_with_two_phones_is_told_once() -> None:
    me = uuid4()
    db = _Db([_phone(me, "1.12.38", "tl"), _phone(me, "1.12.36", "tl")])
    push = _Push()
    assert await announce(db, push, "1.12.39") == 1  # type: ignore[arg-type]
    # One inbox row for the person; a push to each phone, as it can play it.
    inbox = [c for c in db.calls if c[0] == "execute" and "public.notifications" in c[1][0]]
    assert len(inbox) == 1
    assert inbox[0][1][1] == [me]
    assert sorted((p["channel"], tuple(p["tokens"])) for p in push.sent) == [
        ("app_update_tl_v1", (f"token-{me}-1.12.38",)),
        (APP_UPDATES_CHANNEL, (f"token-{me}-1.12.36",)),
    ]
