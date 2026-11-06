"""Staff alerts in the language each staff member reads RepLiT in (1.3).

A new fire, the coordinator's reminders, a dispatch, an incident routed to a
team, an alarm request and BFP's answer: in the push and the inbox, English or
Tagalog per person, while the sound, tag and data stay as they were. The
English wording is unchanged, so nothing reads differently for English staff.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.integrations.fcm import PushResult
from app.services import incident_notify, staff_copy
from app.workers import coordinator_pings

AREA = uuid4()


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


class _StaffDb:
    """Two (or more) staff, each with a language and one phone."""

    def __init__(self, people: dict[UUID, str], designation: str | None = "Area 1.2") -> None:
        self.people = people
        self.designation = designation

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.areas a" in query:
            return {"designation": self.designation, "asked": ["fire_volunteer"]}
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "select designation from public.areas" in query:
            return self.designation
        if "select full_name from public.users" in query:
            return "Juan Dela Cruz"
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "select id, language from public.users" in query:
            return [{"id": u, "language": lang} for u, lang in self.people.items()]
        if "from public.device_tokens" in query:
            if "user_id = $1" in query:
                return [{"user_id": args[0], "fcm_token": f"tok-{args[0]}"}]
            return [{"user_id": u, "fcm_token": f"tok-{u}"} for u in self.people]
        if "role in ('sub_admin', 'response_team')" in query:
            return [
                {"id": u, "role": "response_team", "agency_type": "fire_volunteer"}
                for u in self.people
            ]
        if "role = 'sub_admin'" in query:
            return [{"id": u} for u in self.people]
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> tuple[_Push, list[tuple[list[UUID], str, str]]]:
    push = _Push()
    inbox: list[tuple[list[UUID], str, str]] = []

    async def record(_db: Any, ids: list[UUID], _type: str, title: str, body: str, *_: Any) -> int:
        inbox.append((list(ids), title, body))
        return len(ids)

    async def no_pings(*_: Any) -> None:
        return None

    monkeypatch.setattr(incident_notify, "record_inbox", record)
    monkeypatch.setattr(incident_notify, "PushService", lambda: push)
    monkeypatch.setattr(incident_notify, "start_pings", no_pings)
    return push, inbox


def _two() -> tuple[UUID, UUID, dict[UUID, str]]:
    english, tagalog = uuid4(), uuid4()
    return english, tagalog, {english: "en", tagalog: "tl"}


# --------------------------------------------------------------------------- #
# The words
# --------------------------------------------------------------------------- #
def test_the_english_is_what_staff_already_read() -> None:
    assert staff_copy.new_fire("en", "Area 1.2") == (
        "Fire reported: Area 1.2",
        "A resident reported a fire. Tap to open it, verify it and respond.",
    )
    assert staff_copy.reminder("en", None)[1] == (
        "Still waiting for you. Tap to open it and acknowledge."
    )
    assert staff_copy.dispatched("en", "Area 1.2", "Driver", "Truck 1") == (
        "You've been dispatched",
        "Respond to Area 1.2 — Driver on Truck 1.",
    )
    assert staff_copy.alarm_requested("en", None, "Hercules", "2nd alarm", None) == (
        "Alarm escalation requested",
        "A responder (Hercules) asked for 2nd alarm on an incident.",
    )
    assert staff_copy.alarm_answered("en", False, "2nd alarm", None, "Under control.") == (
        "BFP declined your alarm request",
        "The incident stays as it is. Under control.",
    )


def test_every_staff_message_has_its_tagalog() -> None:
    pairs = [
        (staff_copy.new_fire, ("Area 1.2",)),
        (staff_copy.reminder, ("Area 1.2",)),
        (staff_copy.dispatched, ("Area 1.2", "Driver", "Truck 1")),
        (staff_copy.routed, ("Area 1.2",)),
        (staff_copy.alarm_requested, ("Juan", "Hercules", "2nd alarm", "1.2")),
        (staff_copy.alarm_answered, (True, "2nd alarm", "1.2")),
        (staff_copy.alarm_answered, (False, "2nd alarm", None)),
    ]
    for make, args in pairs:
        english, tagalog = make("en", *args), make("tl", *args)  # type: ignore[operator]
        assert english != tagalog, make
        assert all(part.strip() for part in tagalog)
    # BFP's alarm words and Area names are kept as they are said.
    assert "2nd alarm" in staff_copy.alarm_answered("tl", True, "2nd alarm", "1.2")[1]
    assert "Area 1.2" in staff_copy.alarm_answered("tl", True, "2nd alarm", "1.2")[1]


# --------------------------------------------------------------------------- #
# Each alert, to an English and a Tagalog reader at once
# --------------------------------------------------------------------------- #
async def test_a_new_fire_reaches_each_in_their_language(sent: Any) -> None:
    push, inbox = sent
    english, tagalog, people = _two()
    notified = await incident_notify.notify_staff_new_incident(_StaffDb(people), AREA)  # type: ignore[arg-type]
    assert notified == 2
    by_title = {s["title"]: s["tokens"] for s in push.sent}
    assert by_title == {
        "Fire reported: Area 1.2": [f"tok-{english}"],
        "May ini-report na sunog: Area 1.2": [f"tok-{tagalog}"],
    }
    assert {s["tag"] for s in push.sent} == {f"incident-{AREA}"}
    assert sorted((ids, title) for ids, title, _ in inbox) == sorted(
        [([english], "Fire reported: Area 1.2"), ([tagalog], "May ini-report na sunog: Area 1.2")]
    )


async def test_a_dispatch_in_tagalog(sent: Any) -> None:
    push, inbox = sent
    responder = uuid4()
    await incident_notify.notify_responder_dispatched(
        _StaffDb({responder: "tl"}),  # type: ignore[arg-type]
        responder,
        AREA,
        vehicle_name="Truck 1",
        crew_role="Driver",
    )
    (push_sent,) = push.sent
    assert (push_sent["title"], push_sent["body"]) == (
        "Na-dispatch ka",
        "Tumugon sa Area 1.2 — Driver sakay ng Truck 1.",
    )
    assert inbox[0][1] == "Na-dispatch ka"


async def test_a_routed_incident_reaches_each_captain_in_their_language(sent: Any) -> None:
    push, inbox = sent
    english, tagalog, people = _two()
    captains = await incident_notify.notify_route_recipients(
        _StaffDb(people),  # type: ignore[arg-type]
        AREA,
        [("pnp", None)],
    )
    assert captains == 2
    assert {s["title"]: s["tokens"] for s in push.sent} == {
        "Incident routed to your team": [f"tok-{english}"],
        "May insidenteng ipinasa sa team mo": [f"tok-{tagalog}"],
    }
    assert len(inbox) == 2


async def test_an_alarm_request_reaches_bfp_in_their_language(sent: Any) -> None:
    push, _ = sent
    english, tagalog, people = _two()
    await incident_notify.notify_bfp_alarm_request(
        _StaffDb(people),  # type: ignore[arg-type]
        AREA,
        uuid4(),
        "second_alarm",
        organization="Hercules",
    )
    bodies = {s["tokens"][0]: s["body"] for s in push.sent}
    assert bodies[f"tok-{english}"] == "Juan Dela Cruz (Hercules) asked for 2nd alarm on Area 1.2."
    assert bodies[f"tok-{tagalog}"] == (
        "Humiling si Juan Dela Cruz (Hercules) ng 2nd alarm para sa Area 1.2."
    )
    assert {s["sound"] for s in push.sent} == {"fire"}, "still the alarm, in both"


@pytest.mark.parametrize(
    ("status", "title", "body"),
    [
        (
            "approved",
            "Itinaas ng BFP ang alarma",
            "Nasa 2nd alarm na ang Area 1.2, gaya ng hiniling mo.",
        ),
        (
            "rejected",
            "Hindi inaprubahan ng BFP ang hiling mong alarma",
            "Walang babaguhin sa Area 1.2. Kontrolado na.",
        ),
    ],
)
async def test_bfps_answer_in_tagalog(sent: Any, status: str, title: str, body: str) -> None:
    push, _ = sent
    asker = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        status=status,
        area_id=AREA,
        area_designation="1.2",
        requested_alarm_level="second_alarm",
        requested_by=asker,
        review_notes="Kontrolado na.",
    )
    await incident_notify.notify_alarm_request_answered(_StaffDb({asker: "tl"}), request)  # type: ignore[arg-type]
    (push_sent,) = push.sent
    assert (push_sent["title"], push_sent["body"]) == (title, body)


async def test_a_coordinators_reminder_in_tagalog() -> None:
    push = _Push()
    coordinator = uuid4()
    row = {
        "area_id": AREA,
        "user_id": coordinator,
        "designation": "Area 1.2",
        "agency_type": "fire_volunteer",
        "language": "tl",
    }
    await coordinator_pings._send_reminder(
        _StaffDb({coordinator: "tl"}),  # type: ignore[arg-type]
        push,  # type: ignore[arg-type]
        row,
        sound=True,
    )
    (push_sent,) = push.sent
    assert push_sent["title"] == "May ini-report na sunog: Area 1.2"
    assert push_sent["body"] == "Hinihintay ka pa. I-tap para buksan at i-acknowledge ito."


async def test_a_lookup_that_fails_still_alerts_in_english(sent: Any) -> None:
    push, _ = sent
    responder = uuid4()

    class _Broken(_StaffDb):
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            if "select id, language" in query:
                raise RuntimeError("database went away")
            return await super().fetch(query, *args)

    await incident_notify.notify_responder_dispatched(
        _Broken({responder: "tl"}),  # type: ignore[arg-type]
        responder,
        AREA,
    )
    (push_sent,) = push.sent
    assert push_sent["title"] == "You've been dispatched"


# --------------------------------------------------------------------------- #
# The account's language comes back with /auth/me
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", ["general_user", "response_team", "admin"])
def test_me_says_which_language_the_account_reads(role: str) -> None:
    """So the app on a new phone, and the Admin console, start in it."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.main import app
    from app.schemas.auth import AuthenticatedUser

    user = AuthenticatedUser(id=uuid4(), role=role, language="tl")
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            assert client.get("/auth/me").json()["language"] == "tl"
    finally:
        app.dependency_overrides.clear()


def test_an_account_with_no_choice_reads_english() -> None:
    from app.schemas.auth import AuthenticatedUser

    assert AuthenticatedUser(id=uuid4(), role="admin").language == "en"
