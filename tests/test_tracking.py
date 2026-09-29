"""Track It Live and automatic On scene (hermetic).

What these pin:
- arrival is declared only on consecutive, precise, fresh fixes inside the
  radius — one good reading, an imprecise one, or a late queue of old ones
  cannot move an incident;
- the GPS arrival is the same transition as the Arrived button: row lock,
  audit row (saying it was the GPS, and how close), broadcast, reporter push —
  and it loses quietly to a button pressed first;
- what a citizen receives names no person: units are trucks or "Unit N";
- only the citizen who reported an incident may follow it, over REST or socket,
  and a responder's fix reaches that citizen's socket as a fresh snapshot.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import incidents
from app.api.routes import ws as ws_route
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import tracking
from app.services.tracking import (
    Fix,
    arrival_distance,
    build_tracking_snapshot,
    can_track,
    haversine_m,
    units_from_rows,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "arrival_radius_meters", 100.0)
    monkeypatch.setattr(s, "arrival_consecutive_fixes", 2)
    monkeypatch.setattr(s, "responder_fix_max_age_seconds", 120)
    monkeypatch.setattr(s, "tracking_stale_after_seconds", 60)
    monkeypatch.setattr(s, "require_citizen_phone_verification", True)


NOW = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
FIRE = (14.5378, 121.0014)  # an Area centroid in Pasay
AREA = uuid4()


def _north_of(metres: float) -> tuple[float, float]:
    return FIRE[0] + metres / 111_195.0, FIRE[1]


def _fix(
    metres: float = 30,
    *,
    accuracy: float | None = 12,
    age_s: float = 3,
    captured_age_s: float | None = None,
) -> Fix:
    lat, lng = _north_of(metres)
    return Fix(
        lat=lat,
        lng=lng,
        accuracy_m=accuracy,
        captured_at=NOW - timedelta(seconds=age_s if captured_age_s is None else captured_age_s),
        received_at=NOW - timedelta(seconds=age_s),
    )


def _arrival(fixes: list[Fix]) -> float | None:
    return arrival_distance(
        fixes, FIRE, radius_m=100, needed=2, max_age_s=120, now=NOW
    )


# --------------------------------------------------------------------------- #
# Arrival rules
# --------------------------------------------------------------------------- #
def test_distance_is_measured_in_metres() -> None:
    assert haversine_m(*FIRE, *_north_of(100)) == pytest.approx(100, abs=0.5)
    assert haversine_m(*FIRE, *FIRE) == 0


def test_two_close_precise_fresh_fixes_mean_on_scene() -> None:
    distance = _arrival([_fix(30, age_s=1), _fix(60, age_s=6)])
    assert distance == pytest.approx(30, abs=0.5)


@pytest.mark.parametrize(
    ("fixes", "why"),
    [
        ([_fix(30)], "one good reading is not enough"),
        ([_fix(30), _fix(140)], "the one before was still outside"),
        ([_fix(30), _fix(30, accuracy=250)], "a fix that could be 250 m off proves nothing"),
        ([_fix(30), _fix(30, accuracy=None)], "no accuracy, no proof"),
        ([_fix(30), _fix(30, age_s=300)], "received too long ago"),
        ([_fix(30), _fix(30, captured_age_s=900)], "an old fix sent late"),
        ([_fix(30), _fix(30, captured_age_s=-900)], "stamped in the future"),
        ([], "no fixes at all"),
    ],
)
def test_arrival_is_not_declared_on_weak_evidence(fixes: list[Fix], why: str) -> None:
    assert _arrival(fixes) is None, why


def test_a_radius_is_configurable_and_bounded() -> None:
    fields = type(get_settings()).model_fields
    assert fields["arrival_radius_meters"].default == 100
    meta = {type(m).__name__: m for m in fields["arrival_radius_meters"].metadata}
    assert meta["Le"].le == 500, "an excessively large radius is refused at startup"


# --------------------------------------------------------------------------- #
# The unit list a citizen sees
# --------------------------------------------------------------------------- #
def _row(
    unit_no: int,
    *,
    vehicle: str | None = None,
    fix_age_s: float | None = 5,
    metres: float = 400,
) -> dict[str, Any]:
    lat, lng = _north_of(metres)
    received = None if fix_age_s is None else NOW - timedelta(seconds=fix_age_s)
    return {
        "unit_no": unit_no,
        "vehicle_name": vehicle,
        "org_name": "Hercules Fire Brigade",
        "agency": "fire_volunteer",
        "lat": None if received is None else lat,
        "lng": None if received is None else lng,
        "heading_deg": 180.0,
        "speed_mps": 9.5,
        "accuracy_m": 8.0,
        "received_at": received,
    }


def test_a_trucks_crew_is_one_marker_at_the_freshest_fix() -> None:
    rows = [
        _row(1, vehicle="Apollo", fix_age_s=20, metres=500),
        _row(2, vehicle="apollo ", fix_age_s=2, metres=450),
        _row(3, fix_age_s=4),
    ]
    units = units_from_rows(rows, now=NOW, stale_after_s=60)
    assert [(u.key, u.label) for u in units] == [("unit-1", "apollo"), ("unit-3", "Unit 3")]
    assert units[0].lat == pytest.approx(_north_of(450)[0], abs=1e-6)


def test_silence_is_shown_as_stale_not_hidden() -> None:
    units = units_from_rows(
        [_row(1, fix_age_s=90), _row(2, fix_age_s=None)], now=NOW, stale_after_s=60
    )
    assert [u.stale for u in units] == [True, True]
    assert units[0].lat is not None, "last known position is still drawn, greyed"
    assert units[1].lat is None, "never sent a fix: nothing to draw yet"


class _SnapshotDb:
    """Answers the two snapshot reads; records whether the unit list was read."""

    def __init__(self, status: str, rows: list[dict[str, Any]]) -> None:
        self.status = status
        self.rows = rows
        self.read_units = False

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        assert "from public.areas" in query
        return {
            "id": args[0], "designation": "Area 3", "status": self.status,
            "centroid_lat": FIRE[0], "centroid_lng": FIRE[1],
        }

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        assert "from public.dispatch_logs" in query
        self.read_units = True
        return self.rows


async def test_the_snapshot_names_no_person() -> None:
    db = _SnapshotDb("en_route", [_row(1, vehicle="Apollo"), _row(2)])
    snapshot = await build_tracking_snapshot(db, AREA, now=NOW)  # type: ignore[arg-type]
    assert snapshot is not None
    body = json.dumps(snapshot.model_dump(mode="json"))
    for forbidden in ("responder_id", "user_id", "full_name", "phone", "email", "mobile"):
        assert forbidden not in body
    assert set(snapshot.responders[0].model_dump()) == {
        "key", "label", "organization", "agency", "lat", "lng", "heading_deg",
        "speed_mps", "accuracy_m", "updated_at", "stale",
    }


@pytest.mark.parametrize("status", ["reported", "verified", "fire_out", "closed", "rejected"])
async def test_no_positions_outside_en_route_and_arrived(status: str) -> None:
    db = _SnapshotDb(status, [_row(1)])
    snapshot = await build_tracking_snapshot(db, AREA, now=NOW)  # type: ignore[arg-type]
    assert snapshot is not None and snapshot.responders == []
    assert not db.read_units


# --------------------------------------------------------------------------- #
# Who may follow
# --------------------------------------------------------------------------- #
class _ExistsDb:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.queries: list[str] = []

    async def fetchval(self, query: str, *args: Any) -> bool:
        self.queries.append(query)
        return self.answer


async def test_a_citizen_follows_only_what_they_reported() -> None:
    citizen = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    assert await can_track(_ExistsDb(True), citizen, AREA)  # type: ignore[arg-type]
    no = _ExistsDb(False)
    assert not await can_track(no, citizen, AREA)  # type: ignore[arg-type]
    assert "r.reporter_id = $2" in no.queries[0]


async def test_admin_and_visible_staff_may_follow_too() -> None:
    admin = AuthenticatedUser(id=uuid4(), role="admin")
    assert await can_track(_ExistsDb(False), admin, AREA)  # type: ignore[arg-type]
    crew = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")
    assert await can_track(_ExistsDb(True), crew, AREA)  # type: ignore[arg-type]
    nobody = AuthenticatedUser(id=uuid4(), role="response_team")
    assert not await can_track(_ExistsDb(True), nobody, AREA)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The GPS arrival transition
# --------------------------------------------------------------------------- #
class _TxnDb:
    """A connection that locks and updates, recording each statement."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_TxnDb]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetchval(self, query: str, *args: Any) -> str:
        assert "for update" in query
        return self.status

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if "set status = 'arrived'" in query:
            self.status = "arrived"
        return "UPDATE 1"


@pytest.fixture
def finished(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, str]]:
    seen: list[tuple[UUID, str]] = []

    async def _finish(_db: Any, incident_id: UUID, event_type: str) -> None:
        seen.append((incident_id, event_type))

    monkeypatch.setattr(incidents, "finish_incident_change", _finish)
    return seen


def _distance(value: float | None) -> Any:
    async def _fake(*_a: Any, **_k: Any) -> float | None:
        return value

    return _fake


async def test_gps_arrival_is_the_arrived_transition_with_its_evidence(
    monkeypatch: pytest.MonkeyPatch, finished: list[tuple[UUID, str]]
) -> None:
    monkeypatch.setattr(incidents, "gps_arrival_distance", _distance(42.04))
    db = _TxnDb("en_route")
    responder = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")

    assert await incidents.arrive_by_gps(db, None, responder, AREA)  # type: ignore[arg-type]

    update, audit = db.executed
    assert "set status = 'arrived'" in update[0]
    assert "insert into public.audit_logs" in audit[0]
    args = audit[1]
    assert args[0] == responder.id and args[3] == "incident.arrived"
    assert json.loads(str(args[7])) == {"status": "en_route"}
    assert json.loads(str(args[8])) == {"status": "arrived"}
    assert json.loads(str(args[9])) == {
        "detected": "gps", "distance_m": 42.0, "radius_m": 100.0, "fixes": 2,
    }
    assert finished == [(AREA, "incident_arrived")], "same broadcast and reporter push"


async def test_a_button_pressed_first_wins_quietly(
    monkeypatch: pytest.MonkeyPatch, finished: list[tuple[UUID, str]]
) -> None:
    monkeypatch.setattr(incidents, "gps_arrival_distance", _distance(20.0))
    db = _TxnDb("arrived")
    responder = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")
    assert not await incidents.arrive_by_gps(db, None, responder, AREA)  # type: ignore[arg-type]
    assert db.executed == [] and finished == []


async def test_a_failing_arrival_check_does_not_fail_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*_a: Any, **_k: Any) -> float | None:
        raise RuntimeError("database hiccup")

    published: list[UUID] = []

    async def _publish(_db: Any, area_id: UUID) -> int:
        published.append(area_id)
        return 0

    monkeypatch.setattr(incidents, "gps_arrival_distance", _boom)
    monkeypatch.setattr(incidents, "publish_tracking", _publish)
    responder = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")
    assert not await incidents.after_responder_fix(object(), None, responder, AREA)  # type: ignore[arg-type]
    assert published == [AREA], "the citizen still sees the truck move"


# --------------------------------------------------------------------------- #
# End to end through the app
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(user: AuthenticatedUser, db: Any) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db


class _RouteDb(_SnapshotDb, _ExistsDb):
    def __init__(self, reporter: bool) -> None:
        _SnapshotDb.__init__(self, "en_route", [_row(1, vehicle="Apollo")])
        _ExistsDb.__init__(self, reporter)


def test_the_reporter_reads_the_snapshot(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True), _RouteDb(True))
    response = client.get(f"/areas/{AREA}/tracking")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "en_route" and body["arrival_radius_m"] == 100
    assert body["responders"][0]["label"] == "Apollo"


def test_another_citizen_may_not(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True), _RouteDb(False))
    assert client.get(f"/areas/{AREA}/tracking").status_code == 403


def test_an_unverified_citizen_is_stopped_at_the_gate(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="general_user"), _RouteDb(True))
    response = client.get(f"/areas/{AREA}/tracking")
    assert response.status_code == 403
    assert response.json()["error"] == "phone_not_verified"


def test_a_citizen_may_not_post_a_location(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True), _RouteDb(True))
    response = client.post(
        f"/incidents/{AREA}/location",
        json={"lat": FIRE[0], "lng": FIRE[1], "captured_at": NOW.isoformat()},
    )
    assert response.status_code == 403


def _socket_user(monkeypatch: pytest.MonkeyPatch, user: AuthenticatedUser) -> None:
    async def _auth(_ws: Any) -> AuthenticatedUser:
        return user

    monkeypatch.setattr(ws_route, "authenticate_websocket", _auth)


def test_an_unverified_citizen_cannot_open_the_socket(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _socket_user(monkeypatch, AuthenticatedUser(id=uuid4(), role="general_user"))
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/ws") as sock:
        sock.receive_json()
    assert closed.value.code == 1008


def test_a_responders_fix_reaches_the_reporters_socket(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    citizen = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    responder = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp")
    _socket_user(monkeypatch, citizen)

    async def _reporter_of(_db: Any, user: AuthenticatedUser, area_id: UUID) -> bool:
        return user is citizen and area_id == AREA

    async def _recorded(*_a: Any, **_k: Any) -> bool:
        return True

    monkeypatch.setattr(ws_route, "can_track", _reporter_of)
    monkeypatch.setattr(incidents, "record_responder_location", _recorded)
    monkeypatch.setattr(incidents, "gps_arrival_distance", _distance(None))
    _as(responder, _RouteDb(True))

    with client.websocket_connect("/ws") as sock:
        assert sock.receive_json()["type"] == "connected"
        # Staff detail stays staff-only, even for the reporter ...
        sock.send_json({"action": "subscribe", "channel": f"incident:{AREA}"})
        assert sock.receive_json()["type"] == "error"
        # ... the sanitised channel is theirs.
        sock.send_json({"action": "subscribe", "channel": f"track:{AREA}"})
        assert sock.receive_json() == {"type": "subscribed", "channel": f"track:{AREA}"}

        posted = client.post(
            f"/incidents/{AREA}/location",
            json={"lat": FIRE[0], "lng": FIRE[1], "accuracy_m": 8,
                  "captured_at": datetime.now(UTC).isoformat()},
        )
        assert posted.status_code == 200, posted.text

        message = sock.receive_json()
        assert message["type"] == "tracking"
        snapshot = message["snapshot"]
        assert snapshot["area_id"] == str(AREA)
        assert [r["label"] for r in snapshot["responders"]] == ["Apollo"]
        assert str(responder.id) not in json.dumps(message)
    assert tracking.manager.channel_size(f"track:{AREA}") == 0, "cleaned up on close"
