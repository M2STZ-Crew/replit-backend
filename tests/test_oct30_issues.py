"""The 30 Oct 2026 issue report (hermetic).

What these pin:
- Issue 03: the Fire agencies' Admins and the central hub manage the shared map,
  on the server, and nobody else's Admin does; every map write leaves an audit row;
  the editor can see what it switched off, and only the editor can.
- Issue 09: "I am safe" is for a resident the alert reached, on a live Area, from
  their own tap; it stands once given.
- Issue 01: the Admin console's own words say "organization".
- Issue 02: the neighbourhood alert is 150 m, and clustering is deliberately not.
- No name in the Admin console is one an adblocker hides.

Issue 11 is in tests/test_alarm_escalation.py, Issue 07 in tests/test_push_status.py.
What these fakes cannot run (the database trigger, the upsert) was exercised on a
real Postgres when this was written; see CHANGELOG.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user, get_database
from app.api.routes import map_layers, notifications
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.session import database
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.notification import NotificationRespondRequest
from app.services.audit import match_audit_rule
from app.services.clustering import _CLUSTER_RADIUS_M
from app.workers.neighborhood import NEIGHBORHOOD_RADIUS_M

_ROOT = Path(__file__).resolve().parents[1]
_ORG = uuid4()


def _admin(agency: str = "barangay", *, hub: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name="Admin", primary_org_id=_ORG, org_name="Org",
        org_agency_type=agency, org_is_active=True, org_is_central_hub=hub,
    )


def _citizen() -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)


# --------------------------------------------------------------------------- #
# Issue 03: Map Settings
# --------------------------------------------------------------------------- #
class _MapDb:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.args: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        self.queries.append(" ".join(query.split()))
        self.args.append(args)
        now = datetime.now(UTC)
        return {
            "id": uuid4(), "name": "Covered court", "latitude": 14.5, "longitude": 121.0,
            "capacity": 40, "address": None, "contact_info": None, "city": "Pasay City",
            "outside_pasay": False, "is_active": True, "created_at": now, "updated_at": now,
            "code": "H-1", "bfp_status": "unknown", "effective_status": "unknown",
            "source": "manual", "barangay": "Barangay 76", "risk_level": "high",
            "centroid_lat": 14.5, "centroid_lng": 121.0, "radius_m": 300.0,
        }

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(" ".join(query.split()))
        return []

    async def execute(self, query: str, *args: Any) -> str:
        self.queries.append(" ".join(query.split()))
        return "DELETE 1"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(user: AuthenticatedUser, db: Any) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db


_SITE = {"name": "Covered court", "latitude": 14.5, "longitude": 121.0}
_EDITORS = pytest.mark.parametrize(
    "user",
    [_admin("fire_volunteer"), _admin("bfp"), _admin(hub=True)],
    ids=["fire_volunteer", "bfp", "central_hub"],
)


def test_the_tests_have_no_database_to_write_to(client: TestClient) -> None:
    """The audit middleware writes through the app's own pool, past every override."""
    assert not database.is_connected


@_EDITORS
def test_the_fire_agencies_and_the_hub_edit_the_map(
    client: TestClient, user: AuthenticatedUser
) -> None:
    db = _MapDb()
    _wire(user, db)
    site = uuid4()
    assert client.post("/map/evacuation-sites", json=_SITE).status_code == 201
    assert client.patch(f"/map/evacuation-sites/{site}", json={"capacity": 60}).status_code == 200
    assert client.delete(f"/map/evacuation-sites/{site}").status_code == 204
    assert [q.split()[0] for q in db.queries] == ["insert", "update", "delete"]


@_EDITORS
def test_a_risk_zone_and_its_radius_can_be_changed(
    client: TestClient, user: AuthenticatedUser
) -> None:
    db = _MapDb()
    _wire(user, db)
    zone = uuid4()
    body = {"barangay": "Barangay 76", "centroid_lat": 14.5, "centroid_lng": 121.0}
    assert client.post("/map/risk-zones", json={**body, "radius_m": 200}).status_code == 201
    assert client.patch(f"/map/risk-zones/{zone}", json={"radius_m": 300}).status_code == 200
    assert "set radius_m = $2" in db.queries[-1]
    assert db.args[-1] == (zone, 300)
    for bad in (5, 6000):
        assert client.patch(f"/map/risk-zones/{zone}", json={"radius_m": bad}).status_code == 422
    assert client.delete(f"/map/risk-zones/{zone}").status_code == 204


@_EDITORS
def test_a_hydrant_can_be_added_changed_and_deleted(
    client: TestClient, user: AuthenticatedUser
) -> None:
    db = _MapDb()
    _wire(user, db)
    hydrant = uuid4()
    body = {"code": "H-1", "latitude": 14.5, "longitude": 121.0}
    assert client.post("/map/hydrants", json=body).status_code == 201
    changed = client.patch(f"/map/hydrants/{hydrant}", json={"bfp_status": "operational"})
    assert changed.status_code == 200
    assert client.delete(f"/map/hydrants/{hydrant}").status_code == 204
    assert [q.split()[0] for q in db.queries] == ["insert", "update", "delete"]


def test_the_editor_sends_its_whole_form(client: TestClient) -> None:
    """A blank text box arrives as null, and Save sends every field it shows."""
    db = _MapDb()
    _wire(_admin("fire_volunteer"), db)
    zone = {
        "barangay": "Barangay 76", "name": None, "risk_level": "high", "centroid_lat": 14.5,
        "centroid_lng": 121.0, "radius_m": 300, "description": None,
    }
    assert client.patch(f"/map/risk-zones/{uuid4()}", json=zone).status_code == 200
    hydrant = {
        "code": None, "latitude": 14.5, "longitude": 121.0, "address": None,
        "bfp_status": "unknown", "is_active": True,
    }
    assert client.patch(f"/map/hydrants/{uuid4()}", json=hydrant).status_code == 200


@pytest.mark.parametrize(
    "user",
    [_admin("police"), _admin("medical"), _admin("barangay"), _citizen()],
    ids=["police", "medical", "other_barangay", "citizen"],
)
def test_nobody_else_writes_the_shared_map(client: TestClient, user: AuthenticatedUser) -> None:
    db = _MapDb()
    _wire(user, db)
    site = uuid4()
    assert client.post("/map/evacuation-sites", json=_SITE).status_code == 403
    assert client.patch(f"/map/risk-zones/{site}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/map/risk-zones/{site}").status_code == 403
    assert db.queries == [], "refused before anything touched the database"


def test_a_map_element_needs_a_real_location(client: TestClient) -> None:
    db = _MapDb()
    _wire(_admin(hub=True), db)
    for bad in ({"latitude": 91}, {"longitude": 181}, {"name": ""}):
        assert client.post("/map/evacuation-sites", json={**_SITE, **bad}).status_code == 422
    assert db.queries == []


def test_every_admin_keeps_deleting_water_sources(client: TestClient) -> None:
    db = _MapDb()
    _wire(_admin("police"), db)
    assert client.delete(f"/map/hydrants/{uuid4()}").status_code == 204


@pytest.mark.parametrize("path", ["hydrants", "evacuation-sites", "underground-cisterns"])
def test_only_the_editor_sees_what_was_switched_off(client: TestClient, path: str) -> None:
    db = _MapDb()
    _wire(_admin(hub=True), db)
    client.get(f"/map/{path}", params={"include_inactive": "true"})
    assert "where is_active" not in db.queries[-1]
    client.get(f"/map/{path}")
    assert "where is_active" in db.queries[-1]

    _wire(_admin("police"), db)
    client.get(f"/map/{path}", params={"include_inactive": "true"})
    assert "where is_active" in db.queries[-1], "anyone else gets the active ones"


@pytest.mark.parametrize(
    "path",
    ["hydrants", "evacuation-sites", "risk-zones", "bodies-of-water", "underground-cisterns"],
)
def test_a_change_to_the_map_leaves_a_record(path: str) -> None:
    layer = uuid4()
    assert match_audit_rule("POST", f"/map/{path}") == (
        "map_layer.create", "map_layer", None, False
    )
    assert match_audit_rule("PATCH", f"/map/{path}/{layer}") == (
        "map_layer.update", "map_layer", layer, False
    )
    assert match_audit_rule("DELETE", f"/map/{path}/{layer}") == (
        "map_layer.delete", "map_layer", layer, False
    )


def test_reading_the_map_records_nothing() -> None:
    assert match_audit_rule("GET", "/map/hydrants") is None
    assert match_audit_rule("POST", f"/map/hydrants/{uuid4()}/ground-truth") is None


def test_the_active_filter_is_the_only_difference() -> None:
    assert map_layers._active_only(_admin(hub=True), False) == "where is_active"
    assert map_layers._active_only(_admin(hub=True), True) == ""
    assert map_layers._active_only(_citizen(), True) == "where is_active"


# --------------------------------------------------------------------------- #
# Issue 09: "I am safe"
# --------------------------------------------------------------------------- #
class _AlertDb:
    def __init__(
        self,
        *,
        status: str | None = "en_route",
        alerts_sent: int = 1,
        response: str | None = None,
    ) -> None:
        self.state = None if status is None else {
            "status": status, "alerts_sent": alerts_sent, "response": response,
            "responded_at": None,
        }
        self.writes: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return self.state

    async def execute(self, query: str, *args: Any) -> str:
        self.writes.append((" ".join(query.split()), args))
        return "INSERT 0 1"


async def _say(db: _AlertDb, response: str = "safe", area: UUID | None = None) -> None:
    await notifications.respond_to_alert(
        NotificationRespondRequest(area_id=area or uuid4(), response=response),  # type: ignore[arg-type]
        _citizen(),
        db,  # type: ignore[arg-type]
    )


def test_safe_is_an_answer_and_need_help_is_not_yet() -> None:
    assert NotificationRespondRequest(area_id=uuid4(), response="safe").response == "safe"
    # It promises the Coordinator sees where they are; nothing delivers that yet.
    for not_yet in ("need_help", "not_in_area"):
        with pytest.raises(ValidationError):
            NotificationRespondRequest(area_id=uuid4(), response=not_yet)  # type: ignore[arg-type]


async def test_a_resident_the_alert_reached_can_say_they_are_safe() -> None:
    db = _AlertDb()
    area = uuid4()
    await _say(db, area=area)
    [(query, args)] = db.writes
    assert args[0] == area and args[2] == "safe"
    assert "on conflict (area_id, user_id) do update" in query


async def test_nobody_else_can() -> None:
    db = _AlertDb(alerts_sent=0)
    with pytest.raises(ForbiddenError):
        await _say(db)
    assert db.writes == []


@pytest.mark.parametrize("status", ["fire_out", "post_incident_report", "closed", "rejected"])
async def test_a_fire_that_is_over_takes_no_answer(status: str) -> None:
    db = _AlertDb(status=status)
    with pytest.raises(ConflictError):
        await _say(db)
    assert db.writes == []


async def test_a_missing_area_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _say(_AlertDb(status=None))


async def test_report_and_ignore_stay_open_to_anyone() -> None:
    """A self-reporter is opted out of pushes without ever having been alerted."""
    for response in ("report", "ignore"):
        db = _AlertDb(alerts_sent=0, status="closed")
        await _say(db, response)
        assert len(db.writes) == 1


async def test_safe_stands_once_given() -> None:
    db = _AlertDb()
    await _say(db, "report")
    query = db.writes[0][0]
    assert "response::text = 'safe' then public.neighborhood_notifications.response" in query
    assert "then public.neighborhood_notifications.responded_at" in query


@pytest.mark.parametrize(
    ("state", "offered"),
    [
        ({}, True),
        ({"response": "report"}, True),
        ({"response": "safe"}, False),
        ({"alerts_sent": 0}, False),
        ({"status": "fire_out"}, False),
    ],
)
async def test_the_screen_is_told_whether_to_offer_it(
    state: dict[str, Any], offered: bool
) -> None:
    got = await notifications.my_alert_answer(
        uuid4(), _citizen(), _AlertDb(**state)  # type: ignore[arg-type]
    )
    assert got.can_say_safe is offered


# --------------------------------------------------------------------------- #
# Issue 01: Organization
# --------------------------------------------------------------------------- #
def test_the_admin_console_says_organization() -> None:
    """Code lines only: comments are not interface text, and "organization" in an
    API field was never the problem."""
    comment = re.compile(r"^\s*(//|/\*|\*|\{/\*)")
    found = [
        f"{path.relative_to(_ROOT)}:{n}"
        for path in (_ROOT / "admin-web" / "src").rglob("*")
        if path.suffix in (".js", ".jsx")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "organisation" in line.lower() and not comment.match(line)
    ]
    assert found == []


# --------------------------------------------------------------------------- #
# Adblockers
# --------------------------------------------------------------------------- #
def test_no_console_name_is_one_an_adblocker_hides() -> None:
    """Filter lists hide .ad-main, .ad-sidebar and the like on every site, so a
    console drawn from ad- names is a blank page behind a blocker."""
    comment = re.compile(r"^\s*(//|/\*|\*|\{/\*)")
    name = re.compile(r"(?<![\w-])(--)?ad-[a-z]")
    web = _ROOT / "admin-web"
    found = [
        f"{path.relative_to(_ROOT)}:{n}"
        for path in (web / "index.html", *(web / "src").rglob("*"))
        if path.suffix in (".html", ".js", ".jsx", ".css")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if name.search(line) and not comment.match(line)
    ]
    assert found == []


# --------------------------------------------------------------------------- #
# Issue 02: the radii
# --------------------------------------------------------------------------- #
def test_the_alert_is_150_m_and_clustering_is_its_own_setting() -> None:
    assert NEIGHBORHOOD_RADIUS_M == 150
    # Not the alert radius: what joins reports into one Area. PRD v14 says 100 m,
    # the team's issue says 150 m, the code says 300 m; open decision, see CHANGELOG.
    assert _CLUSTER_RADIUS_M == 300
