"""Backend v1.12.29 (12 Nov 2026): "New Update!", and no build number shown.

- "create an "New Update!" notification, the sound to be follow. still
  vibrates" (answered: a push when a release comes out, the phone's own tone
  for now): every 10 minutes the service reads the app's newest release, and
  everyone on an Android phone on an older version is told once per version,
  by push and in their inbox (app/workers/app_updates.py).
- "remove the build number. it is just the version of app will be remain seen
  in any platforms": the APK download page shows the version alone, and reads
  the notes' "What's new:" list (releases before app 1.12.37 said "New for
  testers:").
- "the first fire organization will fill out so that the second or next fire
  organization arrived will not fill that out": only a fire team says what is
  burning, the first to answer; after that only that team corrects it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.integrations.fcm import (
    APP_UPDATES_CHANNEL,
    UPDATES_CHANNEL,
    PushResult,
    android_config,
)
from app.workers import app_updates
from app.workers.app_updates import (
    INBOX_TYPE,
    LATEST_RELEASE_URL,
    announce,
    is_older,
    latest_version,
    update_copy,
    version_from,
)

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Reading the newest release
# --------------------------------------------------------------------------- #
def test_the_version_comes_from_the_release_manifest() -> None:
    assert version_from({"version": "1.12.37", "build": 59}) == "1.12.37"
    for bad in (None, [], {}, {"version": 1}, {"version": "1.12"}, {"version": "v1.12.37"}):
        assert version_from(bad) is None


async def test_the_newest_release_is_read_from_its_manifest() -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"version": "1.12.37", "build": 59})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        assert await latest_version(client) == "1.12.37"
    # The download, not GitHub's API and its 60 requests an hour.
    assert seen == [LATEST_RELEASE_URL]
    assert "api.github.com" not in LATEST_RELEASE_URL


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"version": "soon"}),
    ],
)
async def test_a_release_that_cannot_be_read_tells_nobody(response: httpx.Response) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        assert await latest_version(client) is None


async def test_no_network_tells_nobody() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        assert await latest_version(client) is None


# --------------------------------------------------------------------------- #
# Who is behind
# --------------------------------------------------------------------------- #
def test_a_phone_before_the_release_is_behind_it() -> None:
    assert is_older("1.12.36", "1.12.37")
    # An app before 1.12.37 registered with its build number too.
    assert is_older("1.12.36 (58)", "1.12.37")
    assert is_older("1.9.0", "1.12.37"), "compared as numbers, not text"
    # A phone that never said is told.
    assert is_older(None, "1.12.37")
    assert is_older("", "1.12.37")


def test_a_phone_on_the_release_or_after_it_is_not() -> None:
    assert not is_older("1.12.37", "1.12.37")
    assert not is_older("1.12.38", "1.12.37")
    assert not is_older("1.13.0 (70)", "1.12.37")


def test_the_push_says_new_update_in_the_readers_language() -> None:
    assert update_copy("en", "1.12.37") == (
        "New Update!",
        "RepLiT 1.12.37 is ready. Tap to update.",
    )
    title, body = update_copy("tl", "1.12.37")
    assert title == "May Bagong Update!"
    assert "1.12.37" in body


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
    def __init__(self, db: _Db, invalid: list[str] | None = None) -> None:
        self.db = db
        self.invalid = invalid or []
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.db.calls.append(("push", (kwargs["title"],)))
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]), invalid_tokens=self.invalid)


def _phone(user: UUID, version: str | None, language: str = "en") -> dict[str, Any]:
    return {
        "user_id": user,
        "language": language,
        "fcm_token": f"token-{user}-{version}",
        "app_version": version,
    }


async def test_everyone_behind_hears_of_it_once_by_push_and_inbox() -> None:
    behind, current, ahead, tagalog = uuid4(), uuid4(), uuid4(), uuid4()
    db = _Db(
        [
            _phone(behind, "1.12.36 (58)"),
            _phone(current, "1.12.37"),
            _phone(ahead, "1.12.38"),
            _phone(tagalog, "1.12.30", "tl"),
        ]
    )
    push = _Push(db)
    told = await announce(db, push, "1.12.37")  # type: ignore[arg-type]
    assert told == 2

    # Asked only of Android phones whose owner has not been told of it yet
    # (nor, since v1.12.32, of a newer version: tests/test_v1_12_32.py).
    query, version = db.calls[0][1]
    assert version == "1.12.37"
    assert "d.platform = 'android'" in query
    assert "n.type = 'app_update'" in query
    assert ">= string_to_array($1, '.')::int[]" in query

    by_title = {p["title"]: p for p in push.sent}
    english, filipino = by_title["New Update!"], by_title["May Bagong Update!"]
    assert english["tokens"] == [f"token-{behind}-1.12.36 (58)"]
    assert filipino["tokens"] == [f"token-{tagalog}-1.12.30"]
    for sent in push.sent:
        # Its own channel: the phone's tone for now, and vibration.
        assert sent["channel"] == APP_UPDATES_CHANNEL
        assert sent.get("sound") is None and not sent.get("silent")
        assert sent["data"] == {"type": INBOX_TYPE, "version": "1.12.37"}
        assert sent["tag"] == INBOX_TYPE

    # The inbox row marks them told, and is written before the push goes.
    inbox = [c for c in db.calls if c[0] == "execute" and "public.notifications" in c[1][0]]
    assert len(inbox) == 2
    for call in inbox:
        _, users, type_, _title, _body, data = call[1]
        assert type_ == INBOX_TYPE
        assert json.loads(data) == {"version": "1.12.37"}
        assert set(users) <= {behind, tagalog}
    order = [c[0] for c in db.calls]
    assert order.index("execute") < order.index("push")


async def test_nobody_behind_sends_nothing() -> None:
    db = _Db([_phone(uuid4(), "1.12.37")])
    push = _Push(db)
    assert await announce(db, push, "1.12.37") == 0  # type: ignore[arg-type]
    assert push.sent == []


async def test_a_dead_token_is_switched_off() -> None:
    user = uuid4()
    db = _Db([_phone(user, "1.12.36")])
    dead = f"token-{user}-1.12.36"
    await announce(db, _Push(db, invalid=[dead]), "1.12.37")  # type: ignore[arg-type]
    off = [c for c in db.calls if c[0] == "execute" and "is_active = false" in c[1][0]]
    assert off and off[0][1][1] == [dead]


def test_the_update_channel_has_the_phones_tone_and_vibrates() -> None:
    config = android_config(channel=APP_UPDATES_CHANNEL)
    assert config.notification.channel_id == "app_updates_v1"
    assert config.notification.default_sound is True
    assert config.notification.default_vibrate_timings is True
    # Other updates keep their channel.
    assert android_config().notification.channel_id == UPDATES_CHANNEL


def test_it_runs_only_where_the_service_has_a_public_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert app_updates.should_run() is False
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://replit-backend-2li4.onrender.com")
    assert app_updates.should_run() is True


def test_the_app_starts_and_stops_the_check() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "start_app_updates_scheduler()" in main
    assert "shutdown_app_updates_scheduler()" in main


# --------------------------------------------------------------------------- #
# The download page: the version alone
# --------------------------------------------------------------------------- #
def test_the_download_page_shows_the_version_alone() -> None:
    page = (ROOT / "apk-web" / "index.html").read_text(encoding="utf-8")
    assert "(build " not in page
    assert "function versionOf(release)" in page
    # Older files are shown without their build number too.
    assert "function fileOf(name)" in page
    assert "strong.textContent = fileOf(apk.name);" in page
    # "What's new:" from 1.12.37 on, "New for testers:" before it.
    assert re.search(r"what\['’\]s new\|new for testers", page)


# --------------------------------------------------------------------------- #
# The first fire team says what is burning
# --------------------------------------------------------------------------- #
# "in the fill-out of fire structure, the first fire organization will fill
# out so that the second or next fire organization arrived will not fill that
# out" (answered: the first fire team only; the rest read it).
HERCULES = UUID("00000000-0000-0000-0000-0000000000a1")
BFP = UUID("00000000-0000-0000-0000-0000000000b2")


def test_a_fire_team_answers_while_nobody_has() -> None:
    from app.services.fire_type import assert_may_answer

    for agency, org in (("fire_volunteer", HERCULES), ("bfp", BFP)):
        assert_may_answer(
            agency=agency, org_id=org, answered_by_org=None, answered_by_name=None
        )


@pytest.mark.parametrize("agency", ["police", "medical", "barangay", None])
def test_other_agencies_read_it(agency: str | None) -> None:
    from app.core.exceptions import ForbiddenError
    from app.services.fire_type import assert_may_answer

    with pytest.raises(ForbiddenError) as caught:
        assert_may_answer(
            agency=agency, org_id=uuid4(), answered_by_org=None, answered_by_name=None
        )
    assert caught.value.error_code == "fire_team_only"


def test_the_next_fire_team_finds_it_answered() -> None:
    from app.core.exceptions import ConflictError
    from app.services.fire_type import assert_may_answer

    with pytest.raises(ConflictError) as caught:
        assert_may_answer(
            agency="bfp",
            org_id=BFP,
            answered_by_org=HERCULES,
            answered_by_name="Hercules Fire Brigade",
        )
    assert caught.value.error_code == "fire_type_answered"
    assert caught.value.message == "Hercules Fire Brigade already said what is burning."
    assert caught.value.details["organization_id"] == str(HERCULES)


def test_the_team_that_answered_corrects_it() -> None:
    from app.services.fire_type import assert_may_answer

    assert_may_answer(
        agency="fire_volunteer",
        org_id=HERCULES,
        answered_by_org=HERCULES,
        answered_by_name="Hercules Fire Brigade",
    )


def test_the_incident_says_which_team_answered() -> None:
    from app.schemas.incident import IncidentDetail

    assert {"fire_type_org_id", "fire_type_org_name"} <= set(IncidentDetail.model_fields)
    source = (ROOT / "app" / "api" / "routes" / "incidents.py").read_text(encoding="utf-8")
    route = source[source.index("async def set_fire_type(") :]
    route = route[: route.index("\nasync def ")]
    # Checked for the agency up front, and for the answering team under the
    # Area's lock, so two teams answering at once cannot both win.
    assert route.count("assert_may_answer(") == 2
    assert route.index("_lock_status(conn") < route.index("answered_by_org=answered")
