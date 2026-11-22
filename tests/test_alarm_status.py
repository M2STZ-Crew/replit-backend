"""v1.12.49: the alarm status; declaring Under control; who hears a raise.

22 Nov 2026: "fire alarm status can be seen in any details info"; answered
"Level + situation", "Coordinators declare" and "Staff loud, residents quiet".
The fakes check behaviour; the SQL itself runs against Postgres only.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import alarm_requests, fire_codes
from app.api.routes import under_control as under_control_route
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import alarm_notify, citizen_copy, staff_copy
from app.services.alarm_status import (
    PUBLIC_DETAIL_COLS,
    STAFF_DETAIL_COLS,
    under_control_at_sql,
)

AREA = uuid4()
NOW = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)


class _Scope:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> bool:
        return False


class _Conn:
    def __init__(self, db: _Db) -> None:
        self.db = db

    def transaction(self) -> _Scope:
        return _Scope()

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return await self.db.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        if not self.db.migrated:
            raise asyncpg.exceptions.UndefinedColumnError("no under_control_at")
        if "under_control_at = now()" in query:
            if self.db.status not in args[2] or self.db.under_control:
                return None
            self.db.under_control = True
            return NOW
        assert "under_control_at = null" in query
        if not self.db.under_control:
            return None
        self.db.under_control = False
        return NOW

    async def execute(self, query: str, *args: Any) -> str:
        assert "audit_logs" in query
        self.db.audit.append(args[3])
        return "INSERT 0 1"


class _Acquire:
    def __init__(self, db: _Db) -> None:
        self.db = db

    async def __aenter__(self) -> _Conn:
        return _Conn(self.db)

    async def __aexit__(self, *_: object) -> bool:
        return False


class _Db:
    def __init__(
        self,
        status: str = "arrived",
        *,
        code: str = "FC-2",
        under_control: bool = False,
        migrated: bool = True,
        routed: bool = True,
    ) -> None:
        self.status = status
        self.code = code
        self.under_control = under_control
        self.migrated = migrated
        self.routed = routed
        self.presses = 0
        self.audit: list[str] = []

    def acquire(self) -> _Acquire:
        return _Acquire(self)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.fire_codes" in query:
            return {
                "code_number": self.code, "name": "A code", "target_role": "response_team",
                "target_agency": None, "is_active": True,
            }
        if "insert into public.fire_code_events" in query:
            self.presses += 1
            return {
                "id": uuid4(), "fire_code_id": args[0], "area_id": args[1],
                "pressed_by": args[2], "pressed_at": NOW, "notes": args[3],
            }
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if query.strip().startswith("select status::text"):
            return self.status
        if "dispatch_logs" in query:
            return True  # a responder pressing is on it
        if "select 1 from public.areas" in query:
            return 1
        return self.routed  # visible to the agency, routed to the Admin


def _coordinator(agency: str = "fire_volunteer") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type=agency, full_name="Ben Reyes"
    )


def _admin(agency: str, *, hub: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name="An Admin", primary_org_id=uuid4(),
        org_name="An Org", org_agency_type=agency, org_is_active=True,
        org_is_central_hub=hub,
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[str]]]:
    done: list[str] = []

    async def finish(db: Any, area: UUID, event: str, **_: Any) -> dict[str, Any]:
        done.append(event)
        return {
            "id": area, "designation": "Near F. Victor Street", "status": "arrived",
            "centroid_lat": 14.5, "centroid_lng": 121.0, "report_count": 1,
            "confidence_score": 0.5, "confidence_band": "medium", "reported_at": NOW,
            "updated_at": NOW, "n_score": 0, "s_score": 0, "v_score": 0, "version": 1,
        }

    async def quiet(*_: Any, **__: Any) -> None:
        return None

    def spawn(job: Any) -> None:
        job.close()
        done.append("told")

    monkeypatch.setattr(fire_codes, "finish_incident_change", finish)
    monkeypatch.setattr(fire_codes, "notify_fire_code", quiet)
    monkeypatch.setattr(fire_codes.manager, "broadcast", quiet)
    monkeypatch.setattr(under_control_route, "finish_incident_change", finish)
    monkeypatch.setattr(under_control_route.fire_broadcast, "spawn", spawn)
    with TestClient(app) as client:
        yield client, done
    app.dependency_overrides.clear()


def _post(client: TestClient, db: _Db, user: AuthenticatedUser, path: str) -> Any:
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    body = {"area_id": str(AREA)} if path.endswith("/press") else {}
    return client.post(path, json=body)


def _press(client: TestClient, db: _Db, user: AuthenticatedUser) -> Any:
    return _post(client, db, user, f"/fire-codes/{uuid4()}/press")


def _withdraw(client: TestClient, db: _Db, user: AuthenticatedUser) -> Any:
    return _post(client, db, user, f"/incidents/{AREA}/under-control/withdraw")


# --------------------------------------------------------------------------- #
# Declaring
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["verified", "en_route", "arrived"])
@pytest.mark.parametrize(
    "who",
    [_coordinator(), _coordinator("bfp"), _admin("bfp"), _admin("barangay", hub=True)],
)
def test_fc2_declares_a_live_fire_under_control(
    api: tuple[TestClient, list[str]], who: AuthenticatedUser, status: str
) -> None:
    db = _Db(status)
    assert _press(api[0], db, who).status_code == 201
    assert db.under_control is True
    assert db.presses == 1
    assert db.audit == ["incident.under_control"]


def test_a_responders_fc2_only_tells_command(api: tuple[TestClient, list[str]]) -> None:
    db = _Db()
    crew = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")
    assert _press(api[0], db, crew).status_code == 201
    assert db.presses == 1
    assert db.under_control is False
    assert db.audit == []


def test_another_code_declares_nothing(api: tuple[TestClient, list[str]]) -> None:
    db = _Db(code="FC-6")
    assert _press(api[0], db, _coordinator()).status_code == 201
    assert db.under_control is False


def test_not_before_it_is_acknowledged(api: tuple[TestClient, list[str]]) -> None:
    db = _Db("reported")
    assert _press(api[0], db, _coordinator()).status_code == 409
    assert db.presses == 0
    assert db.under_control is False


@pytest.mark.parametrize("status", ["fire_out", "closed"])
def test_after_fire_out_it_is_a_code_only(
    api: tuple[TestClient, list[str]], status: str
) -> None:
    db = _Db(status)
    assert _press(api[0], db, _coordinator()).status_code == 201
    assert db.presses == 1
    assert db.under_control is False


@pytest.mark.parametrize("who", [_coordinator(), _admin("bfp")])
def test_only_on_a_fire_that_is_theirs(
    api: tuple[TestClient, list[str]], who: AuthenticatedUser
) -> None:
    db = _Db(routed=False)
    assert _press(api[0], db, who).status_code == 403
    assert db.presses == 0


def test_declaring_again_keeps_the_first(api: tuple[TestClient, list[str]]) -> None:
    db = _Db(under_control=True)
    assert _press(api[0], db, _coordinator()).status_code == 201
    assert db.audit == []


def test_before_the_migration_the_press_still_stands(api: tuple[TestClient, list[str]]) -> None:
    db = _Db(migrated=False)
    assert _press(api[0], db, _coordinator()).status_code == 201
    assert db.presses == 1
    assert db.audit == []


# --------------------------------------------------------------------------- #
# Withdrawing
# --------------------------------------------------------------------------- #
def test_it_can_be_withdrawn(api: tuple[TestClient, list[str]]) -> None:
    client, done = api
    db = _Db(under_control=True)
    assert _withdraw(client, db, _coordinator("bfp")).status_code == 200
    assert db.under_control is False
    assert db.audit == ["incident.under_control_withdrawn"]
    assert done == ["under_control_withdrawn", "told"]


def test_nothing_to_withdraw(api: tuple[TestClient, list[str]]) -> None:
    client, done = api
    assert _withdraw(client, _Db(), _coordinator()).status_code == 409
    assert done == []


@pytest.mark.parametrize(
    "who",
    [
        _coordinator("police"),
        _admin("police"),
        AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp"),
    ],
)
def test_others_cannot_withdraw(
    api: tuple[TestClient, list[str]], who: AuthenticatedUser
) -> None:
    db = _Db(under_control=True)
    assert _withdraw(api[0], db, who).status_code == 403
    assert db.under_control is True


def test_withdrawing_waits_for_the_migration(api: tuple[TestClient, list[str]]) -> None:
    response = _withdraw(api[0], _Db(migrated=False), _coordinator())
    assert response.status_code == 409
    assert response.json()["error"] == "migration_pending"


# --------------------------------------------------------------------------- #
# What every screen reads
# --------------------------------------------------------------------------- #
def test_a_raise_clears_it_with_nothing_written() -> None:
    sql = under_control_at_sql("a")
    assert ">= coalesce(a.alarm_level_set_at" in sql
    assert "'verified', 'en_route', 'arrived'" in sql


def test_it_reads_before_the_migration() -> None:
    for sql in (under_control_at_sql("areas"), PUBLIC_DETAIL_COLS, STAFF_DETAIL_COLS):
        assert "a.under_control_at" not in sql
        assert "areas.under_control_at" not in sql


def test_residents_get_the_organisation_never_the_person() -> None:
    assert "full_name" not in PUBLIC_DETAIL_COLS
    assert "full_name" in STAFF_DETAIL_COLS


# --------------------------------------------------------------------------- #
# Who hears a raise
# --------------------------------------------------------------------------- #
RAISER, ASKER, CREW, COORDINATOR, NEIGHBOUR, REPORTER = (uuid4() for _ in range(6))


class _AlertDb:
    def __init__(self) -> None:
        self.inbox: list[tuple[set[UUID], str]] = []

    async def fetchval(self, query: str, *args: Any) -> str:
        return "BFP Pasay" if "organizations" in query else "Near F. Victor Street"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "dispatch_logs" in query:
            return [{"id": i} for i in (RAISER, ASKER, CREW, COORDINATOR)]
        if "neighborhood_notifications" in query:
            return [{"id": i} for i in (NEIGHBOUR, REPORTER)]
        if "select id, language" in query:
            return [{"id": i, "language": "tl" if i == NEIGHBOUR else "en"} for i in args[0]]
        assert "device_tokens" in query
        return [
            {"user_id": i, "fcm_token": str(i), "app_version": "1.12.60"} for i in args[0]
        ]

    async def execute(self, query: str, *args: Any) -> str:
        assert "public.notifications" in query
        self.inbox.append((set(args[0]), args[1]))
        return "INSERT 0 1"


class _Push:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_to_tokens(self, **message: Any) -> Any:
        self.sent.append(message)
        return SimpleNamespace(invalid_tokens=[])


async def test_staff_hear_a_raise_and_residents_are_told_quietly() -> None:
    db, push = _AlertDb(), _Push()
    counts = await alarm_notify.notify_alarm_raised(
        db, AREA, "third_alarm", RAISER, already_told=[ASKER], push=push,  # type: ignore[arg-type]
    )
    assert counts == (2, 2)
    loud = {t for m in push.sent if not m["silent"] for t in m["tokens"]}
    silent = {t for m in push.sent if m["silent"] for t in m["tokens"]}
    assert loud == {str(CREW), str(COORDINATOR)}
    assert silent == {str(NEIGHBOUR), str(REPORTER)}
    assert all(m["sound"] == ("fire" if not m["silent"] else None) for m in push.sent)
    assert set().union(*(ids for ids, _ in db.inbox)) == {CREW, COORDINATOR, NEIGHBOUR, REPORTER}
    assert {kind for _, kind in db.inbox} == {"alarm_raised"}


async def test_a_withdrawal_is_told_to_staff_quietly() -> None:
    db, push = _AlertDb(), _Push()
    told = await alarm_notify.notify_under_control_withdrawn(
        db, AREA, RAISER, push=push,  # type: ignore[arg-type]
    )
    assert told == 3
    assert all(m["silent"] for m in push.sent)
    assert {m["tag"] for m in push.sent} == {f"code-{AREA}-FC-2"}


async def test_a_raise_reaches_open_screens_and_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def detail(db: Any, area: UUID) -> str:
        return "detail"

    async def broadcast(what: str, event: str) -> None:
        seen.append(event)

    async def tracking(db: Any, area: UUID) -> None:
        seen.append("tracking")

    def spawn(job: Any) -> None:
        job.close()
        seen.append("alerts")

    monkeypatch.setattr(alarm_requests, "build_incident_detail", detail)
    monkeypatch.setattr(alarm_requests, "broadcast_incident_event", broadcast)
    monkeypatch.setattr(alarm_requests, "publish_tracking", tracking)
    monkeypatch.setattr(alarm_requests.fire_broadcast, "spawn", spawn)
    await alarm_requests._alert_everyone(
        None, AREA, "second_alarm", RAISER, [ASKER]  # type: ignore[arg-type]
    )
    assert seen == ["alarm_raised", "tracking", "alerts"]


def test_the_words_of_a_raise() -> None:
    title, body = staff_copy.alarm_raised("en", "3rd alarm", "Near F. Victor Street", "BFP Pasay")
    assert title == "Alarm raised: 3rd alarm"
    assert body == "The fire near F. Victor Street is now at 3rd alarm, raised by BFP Pasay."
    title, body = citizen_copy.alarm_raised("en", "3rd alarm", "Near F. Victor Street")
    assert title == "Fire alarm raised"
    assert "now at 3rd alarm" in body
    assert "more firefighters and trucks" in body
    assert "BFP Pasay" not in body
    _, highest = citizen_copy.alarm_raised("en", "General alarm", None, highest=True)
    assert "highest alarm" in highest
    _, tagalog = citizen_copy.alarm_raised("tl", "3rd alarm", "Near F. Victor Street")
    assert "Nasa 3rd alarm" in tagalog
