"""The live citizen map: ``map:areas`` (hermetic).

What these pin:
- a report submitted over HTTP reaches a citizen's open socket as the area's
  summary — the columns GET /areas already shows everyone, nothing more;
- an incident that ends is sent as inactive, so the app takes it off the map;
- every lifecycle change and every merge publishes, and nothing is read while
  nobody watches;
- any signed-in user may follow the map, and a refused subscription names the
  channel it refused.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import get_current_user, get_database, get_storage_client
from app.api.routes import areas as areas_route
from app.api.routes import incidents, reports
from app.api.routes import ws as ws_route
from app.api.routes.ws import authorize_channel
from app.main import app
from app.realtime.manager import manager
from app.schemas.area import AreaSummary
from app.schemas.auth import AuthenticatedUser
from app.services.map_feed import MAP_CHANNEL, publish_area_change

AREA = uuid4()
NOW = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def _summary(status: str = "reported") -> dict[str, Any]:
    return {
        "id": AREA,
        "designation": "Area 7",
        "status": status,
        "centroid_lat": 14.5378,
        "centroid_lng": 121.0014,
        "report_count": 2,
        "confidence_score": 0.41,
        "confidence_band": "medium",
        "alarm_level": None,
        "reported_at": NOW,
        "updated_at": NOW,
    }


class _Db:
    """Answers a report submit and the map's one read."""

    def __init__(self, status: str = "reported", active: bool = True) -> None:
        self.status = status
        self.active = active
        self.reads = 0

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "as active" in query:
            self.reads += 1
            return {**_summary(self.status), "active": self.active}
        if "from public.reports r" in query and "area_reports" in query:
            return None  # nothing else in progress
        if "insert into public.reports" in query:
            return {"id": args[0], "created_at": NOW}
        if "from public.areas" in query:
            return {
                "designation": "Area 7",
                "centroid_lat": 14.5378,
                "centroid_lng": 121.0014,
                "report_count": 1,
            }
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "UPDATE 1"


class _Socket:
    """Stands in for one open socket in the connection manager."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


@pytest.fixture
def watcher() -> Iterator[_Socket]:
    socket = _Socket()
    conn = manager.connect(socket, AuthenticatedUser(id=uuid4(), role="general_user"))  # type: ignore[arg-type]
    manager.subscribe(conn, MAP_CHANNEL)
    yield socket
    manager.disconnect(conn)


async def test_nothing_is_read_while_nobody_watches() -> None:
    db = _Db()
    assert await publish_area_change(db, AREA) == 0  # type: ignore[arg-type]
    assert db.reads == 0


async def test_a_change_is_sent_as_the_areas_summary(watcher: _Socket) -> None:
    assert await publish_area_change(_Db(status="en_route"), AREA) == 1  # type: ignore[arg-type]
    [message] = watcher.sent
    assert message["type"] == "area" and message["channel"] == MAP_CHANNEL
    assert message["active"] is True
    assert set(message["area"]) == set(AreaSummary.model_fields), "nothing GET /areas hides"
    assert message["area"]["status"] == "en_route"


async def test_an_incident_that_ends_leaves_the_map(watcher: _Socket) -> None:
    await publish_area_change(_Db(status="fire_out", active=False), AREA)  # type: ignore[arg-type]
    assert watcher.sent[0]["active"] is False


async def test_a_failed_read_never_fails_the_change(watcher: _Socket) -> None:
    class _Broken:
        async def fetchrow(self, *_a: Any) -> None:
            raise RuntimeError("database hiccup")

    assert await publish_area_change(_Broken(), AREA) == 0  # type: ignore[arg-type]


async def test_every_lifecycle_change_reaches_the_map(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[UUID] = []

    async def _nothing(*_a: Any, **_k: Any) -> Any:
        return None

    async def _publish(_db: Any, area_id: UUID) -> int:
        published.append(area_id)
        return 1

    monkeypatch.setattr(incidents, "build_incident_detail", _nothing)
    monkeypatch.setattr(incidents, "broadcast_incident_event", _nothing)
    monkeypatch.setattr(incidents, "publish_tracking", _nothing)
    monkeypatch.setattr(incidents, "notify_incident_reporters", _nothing)
    monkeypatch.setattr(incidents, "publish_area_change", _publish)
    await incidents.finish_incident_change(object(), AREA, "incident_verified")  # type: ignore[arg-type]
    assert published == [AREA]


async def test_everyone_signed_in_may_follow_the_map() -> None:
    for user in (
        AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True),
        AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp"),
        AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="police"),
    ):
        assert await authorize_channel(user, MAP_CHANNEL, object())  # type: ignore[arg-type]
    citizen = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    assert not await authorize_channel(citizen, "map:secret", object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Through the app
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _Storage:
    async def upload(self, **_: Any) -> None:
        return None


def test_a_submitted_report_appears_on_an_open_map(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    watcher = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    reporter = AuthenticatedUser(
        id=uuid4(), role="general_user", phone_verified=True, verified_percent=40
    )

    async def _auth(_ws: Any) -> AuthenticatedUser:
        return watcher

    async def _cluster(*_a: Any, **_k: Any) -> UUID:
        return AREA

    async def _quiet(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(ws_route, "authenticate_websocket", _auth)
    monkeypatch.setattr(reports, "cluster_report", _cluster)
    monkeypatch.setattr(reports, "notify_area_neighbors", _quiet)
    monkeypatch.setattr(reports, "notify_staff_new_incident", _quiet)
    app.dependency_overrides[get_current_user] = lambda: reporter
    app.dependency_overrides[get_database] = lambda: _Db()
    app.dependency_overrides[get_storage_client] = lambda: _Storage()

    photo = BytesIO()
    Image.new("RGB", (12, 8), "red").save(photo, format="PNG")

    with client.websocket_connect("/ws") as sock:
        assert sock.receive_json()["type"] == "connected"
        # A refusal says which channel it refused.
        sock.send_json({"action": "subscribe", "channel": f"incident:{AREA}"})
        refused = sock.receive_json()
        assert refused["type"] == "error" and refused["channel"] == f"incident:{AREA}"
        sock.send_json({"action": "subscribe", "channel": MAP_CHANNEL})
        assert sock.receive_json() == {"type": "subscribed", "channel": MAP_CHANNEL}

        response = client.post(
            "/reports/submit",
            data={"device_lat": "14.5378", "device_lng": "121.0014",
                  "selected_agencies": "fire_volunteer"},
            files={"photo": ("fire.png", photo.getvalue(), "image/png")},
        )
        assert response.status_code == 201, response.text

        message = sock.receive_json()
        assert message["type"] == "area" and message["active"] is True
        assert message["area"]["id"] == str(AREA)
        assert str(reporter.id) not in json.dumps(message), "no reporter on the map"


def test_a_merge_updates_both_areas_on_the_map(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep, drop = uuid4(), uuid4()

    class _MergeDb:
        async def fetchrow(self, *_a: Any) -> dict[str, Any]:
            return {"area_a_id": keep, "area_b_id": drop, "decision": None,
                    "expires_at": datetime.now(UTC) + timedelta(seconds=60)}

        async def fetchval(self, *_a: Any) -> str:
            return "reported"

        async def execute(self, *_a: Any) -> str:
            return "UPDATE 1"

    published: list[UUID] = []

    async def _publish(_db: Any, area_id: UUID) -> int:
        published.append(area_id)
        return 1

    async def _recompute(*_a: Any) -> None:
        return None

    monkeypatch.setattr(areas_route, "publish_area_change", _publish)
    monkeypatch.setattr(areas_route, "recompute_area", _recompute)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type="fire_volunteer"
    )
    app.dependency_overrides[get_database] = lambda: _MergeDb()
    response = client.post(f"/areas/overlaps/{uuid4()}/merge")
    assert response.status_code == 200, response.text
    assert published == [keep, drop]
