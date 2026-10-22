"""A coordinator who does not open a new fire is reminded (hermetic, v1.12.9).

What these pin (PRD v14 §4.13.2):
- the cycle: vibrate only at +2 min, their agency's sound at +5, vibrate only
  at +7, the sound at +10, then it stops;
- it stops early when the incident leaves the live feed or their agency
  acknowledges it, and when they open it (POST /incidents/{id}/seen);
- a step is claimed before it is sent, so it is never sent twice.

Nothing here talks to Firebase or a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.integrations.fcm import PushResult
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.workers.coordinator_pings import SCHEDULE, run_pings

AREA = uuid4()
CAPTAIN = uuid4()


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **kwargs: Any) -> PushResult:
        self.sent.append(kwargs)
        return PushResult(success_count=len(kwargs["tokens"]))


class _Db:
    """One running cycle, at ``step``, ``age`` seconds after the first push."""

    def __init__(
        self,
        *,
        step: int,
        age: float,
        agency: str = "police",
        live: bool = True,
        acknowledged: bool = False,
        claim: bool = True,
    ) -> None:
        self.row = {
            "area_id": AREA,
            "user_id": CAPTAIN,
            "step": step,
            "designation": "Area 7",
            "agency_type": agency,
            "age": age,
            "live": live,
            "acknowledged": acknowledged,
        }
        self.claim = claim
        self.stopped: list[str] = []
        self.claims: list[tuple[Any, ...]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.coordinator_pings p" in query:
            return [self.row]
        if "device_tokens" in query:
            return [{"fcm_token": "tok"}]
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "stop_reason = $3" in query:
            self.stopped.append(args[2])
            return {"area_id": args[0]}
        if "set step = step + 1" in query:
            self.claims.append(args)
            return {"step": args[2] + 1} if self.claim else None
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def test_the_schedule_is_the_prds() -> None:
    assert SCHEDULE == ((120, False), (300, True), (420, False), (600, True))


async def test_nothing_before_two_minutes() -> None:
    push = _Push()
    assert await run_pings(_Db(step=0, age=119), push) == 0  # type: ignore[arg-type]
    assert push.sent == []


async def test_two_minutes_vibrates_without_a_sound() -> None:
    push, db = _Push(), _Db(step=0, age=121)
    assert await run_pings(db, push) == 1  # type: ignore[arg-type]
    [sent] = push.sent
    assert sent["silent"] is True and sent["sound"] is None
    assert sent["tag"] == f"incident-{AREA}", "replaces the first push in the shade"
    assert sent["data"]["type"] == "incident_reminder"
    assert db.claims == [(AREA, CAPTAIN, 0, False)]


async def test_five_minutes_plays_their_agencys_sound() -> None:
    push = _Push()
    await run_pings(_Db(step=1, age=301, agency="police"), push)  # type: ignore[arg-type]
    [sent] = push.sent
    assert sent["sound"] == "police" and sent["silent"] is False


async def test_ten_minutes_is_the_last_and_closes_the_cycle() -> None:
    push, db = _Push(), _Db(step=3, age=601, agency="bfp")
    assert await run_pings(db, push) == 1  # type: ignore[arg-type]
    assert push.sent[0]["sound"] == "fire"
    assert db.claims == [(AREA, CAPTAIN, 3, True)], "the claim also stops it"


async def test_a_step_another_server_claimed_is_not_sent_again() -> None:
    push = _Push()
    assert await run_pings(_Db(step=0, age=200, claim=False), push) == 0  # type: ignore[arg-type]
    assert push.sent == []


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"live": False}, "closed"),
        ({"acknowledged": True}, "acknowledged"),
        ({"step": 4}, "done"),
    ],
)
async def test_it_stops_early(kwargs: dict[str, Any], reason: str) -> None:
    push = _Push()
    db = _Db(**{"step": 0, "age": 400, **kwargs})
    assert await run_pings(db, push) == 0  # type: ignore[arg-type]
    assert db.stopped == [reason] and push.sent == []


# --------------------------------------------------------------------------- #
# Opening the incident stops them
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _SeenDb:
    def __init__(self, running: bool) -> None:
        self.running = running
        self.calls: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(args)
        return {"area_id": args[0]} if self.running else None


@pytest.mark.parametrize(
    ("running", "message"), [(True, "Reminders stopped."), (False, "No reminders running.")]
)
def test_opening_the_incident_stops_the_reminders(
    client: TestClient, running: bool, message: str
) -> None:
    db = _SeenDb(running)
    user = AuthenticatedUser(id=CAPTAIN, role="sub_admin", agency_type="police")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db

    resp = client.post(f"/incidents/{AREA}/seen")

    assert resp.status_code == 200 and resp.json()["message"] == message
    assert db.calls == [(AREA, CAPTAIN, "opened")]


def test_a_resident_cannot_call_it(client: TestClient) -> None:
    user = AuthenticatedUser(id=uuid4(), role="general_user", agency_type=None)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: _SeenDb(True)
    assert client.post(f"/incidents/{AREA}/seen").status_code == 403

