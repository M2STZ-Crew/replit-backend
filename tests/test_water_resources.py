"""v1.12.43: water resources managed from the field, one place in the console.

19 Nov 2026, the user's answers: Fire Volunteer and BFP coordinators and
responders set a hydrant's status after checking it (working, low pressure,
broken, no access); coordinators add, change and switch off water sources for
an Admin to approve; residents see where water is, never its status.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import HydrantGroundTruthRequest
from app.services.staff_copy import map_request_decided

NOW = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _gates(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "require_citizen_email_verification", False)
    monkeypatch.setattr(settings, "require_citizen_phone_verification", False)


def _hydrant(**kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(),
        "code": "H-17",
        "latitude": 14.5378,
        "longitude": 121.0014,
        "address": "F. Victor Street, Pasay",
        "bfp_status": "operational",
        "bfp_synced_at": None,
        "ground_truth_status": "low_pressure",
        "ground_truth_by": uuid4(),
        "ground_truth_at": NOW,
        "ground_truth_notes": "Weak flow at 8 PM.",
        "effective_status": "low_pressure",
        "source": "openstreetmap:node/1",
        "is_active": True,
        "created_at": NOW,
        "updated_at": NOW,
        "checked_by_name": "Ana Cruz",
        "checked_by_org": "BFP Pasay",
    }
    row.update(kw)
    return row


class _Db:
    def __init__(self) -> None:
        self.hydrants = [_hydrant()]
        self.inserted: dict[str, Any] | None = None

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if "from public.hydrants" in query:
            return list(self.hydrants)
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "select ground_truth_status::text as gt" in query:
            return {"gt": None}
        if "update public.hydrants" in query:
            return {k: v for k, v in _hydrant(ground_truth_status=args[1]).items()
                    if not k.startswith("checked_by")}
        if "insert into public.map_layer_update_requests" in query:
            self.inserted = {
                "id": uuid4(), "requested_by": args[0], "organization_id": args[1],
                "layer_type": args[2], "operation": args[3], "target_id": args[4],
                "proposed_data": args[5], "reason": args[6], "status": "pending",
                "reviewed_by": None, "reviewed_at": None, "review_notes": None,
                "applied_at": None, "created_at": NOW, "updated_at": NOW,
            }
            return self.inserted
        if "from public.hydrants" in query:
            return self.hydrants[0]
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@pytest.fixture
def db() -> _Db:
    return _Db()


@pytest.fixture
def client(db: _Db) -> Iterator[TestClient]:
    app.dependency_overrides[get_database] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(role: str, agency: str | None = None) -> AuthenticatedUser:
    person = AuthenticatedUser(
        id=uuid4(), role=role, email="staff@example.com", agency_type=agency
    )
    app.dependency_overrides[get_current_user] = lambda: person
    return person


def test_low_pressure_and_no_access_are_statuses() -> None:
    assert HydrantGroundTruthRequest(status="low_pressure").status == "low_pressure"
    assert HydrantGroundTruthRequest(status="no_access").status == "no_access"


@pytest.mark.parametrize(
    ("role", "agency"),
    [
        ("sub_admin", "fire_volunteer"),
        ("sub_admin", "bfp"),
        ("response_team", "fire_volunteer"),
        ("response_team", "bfp"),
    ],
)
def test_fire_coordinators_and_responders_set_a_hydrants_status(
    client: TestClient, role: str, agency: str
) -> None:
    _as(role, agency)
    response = client.post(
        f"/map/hydrants/{uuid4()}/ground-truth",
        json={"status": "no_access", "notes": "A car parked on it."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ground_truth_status"] == "no_access"


@pytest.mark.parametrize(
    ("role", "agency"),
    [("sub_admin", "police"), ("response_team", "medical"), ("general_user", None)],
)
def test_nobody_else_sets_it(client: TestClient, role: str, agency: str | None) -> None:
    _as(role, agency)
    response = client.post(
        f"/map/hydrants/{uuid4()}/ground-truth", json={"status": "operational"}
    )
    assert response.status_code == 403


def test_residents_see_where_hydrants_are_never_their_status(client: TestClient) -> None:
    _as("general_user")
    (resident_view,) = client.get("/map/hydrants").json()
    assert resident_view["latitude"] == 14.5378
    assert resident_view["effective_status"] == "unknown"
    assert resident_view["ground_truth_status"] is None
    assert resident_view["checked_by_org"] is None

    _as("response_team", "bfp")
    (staff_view,) = client.get("/map/hydrants").json()
    assert staff_view["effective_status"] == "low_pressure"
    assert staff_view["checked_by_org"] == "BFP Pasay"


def test_water_changes_are_proposed_by_fire_coordinators(
    client: TestClient, db: _Db
) -> None:
    proposal = {
        "layer_type": "hydrant",
        "operation": "create",
        "proposed_data": {"latitude": 14.54, "longitude": 121.0, "address": "Taft Avenue"},
        "reason": "Found during a run.",
    }
    _as("sub_admin", "police")
    refused = client.post("/map-layer-requests", json=proposal)
    assert refused.status_code == 403
    assert refused.json()["error"] == "not_fire_coordinator"

    _as("sub_admin", "bfp")
    accepted = client.post("/map-layer-requests", json=proposal)
    assert accepted.status_code == 201, accepted.text
    assert db.inserted is not None
    assert json.loads(db.inserted["proposed_data"])["address"] == "Taft Avenue"


def test_the_answer_says_what_was_asked_in_the_readers_language() -> None:
    title, body = map_request_decided(
        "en", approved=True, layer="hydrant", operation="create"
    )
    assert title == "Map change approved"
    assert body == "The hydrant you added is on the map now."
    _, off = map_request_decided(
        "en", approved=False, layer="bodies_of_water", operation="delete",
        notes="It still has water.",
    )
    assert off == "Switching off the body of water was not approved. It still has water."
    tl_title, tl_body = map_request_decided(
        "tl", approved=True, layer="underground_cistern", operation="update"
    )
    assert tl_title == "Naaprubahan ang pagbabago sa mapa"
    assert "cistern" in tl_body


def test_a_coordinators_water_delete_is_a_switch_off_kept_on_record(
    client: TestClient, db: _Db
) -> None:
    _as("sub_admin", "fire_volunteer")
    response = client.post(
        "/map-layer-requests",
        json={
            "layer_type": "bodies_of_water",
            "operation": "delete",
            "target_id": str(uuid4()),
            "reason": "Dried up.",
        },
    )
    assert response.status_code == 201, response.text
    assert db.inserted is not None
    assert db.inserted["operation"] == "update"
    assert json.loads(db.inserted["proposed_data"]) == {"is_active": False}


# --------------------------------------------------------------------------- #
# Before migration 20261120090000: everything else keeps working
# --------------------------------------------------------------------------- #
def _water(**kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(),
        "name": "Tripa de Gallina",
        "water_type": "river",
        "latitude": 14.536,
        "longitude": 121.004,
        "is_accessible": True,
        "description": None,
        "area_geojson": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(kw)
    return row


def _no_column() -> asyncpg.exceptions.UndefinedColumnError:
    return asyncpg.exceptions.UndefinedColumnError('column "is_active" does not exist')


class _BeforeMigration(_Db):
    """No bodies_of_water.is_active, and no "Low pressure" or "No access" yet."""

    def __init__(self) -> None:
        super().__init__()
        self.approved = False

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if "from public.bodies_of_water" in query:
            if "is_active" in query:
                raise _no_column()
            return [_water()]
        return await super().fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "from public.bodies_of_water" in query:
            if "is_active" in query:
                raise _no_column()
            return _water()
        if "update public.bodies_of_water" in query:
            if "is_active" in query:
                raise _no_column()
            return _water(name=args[1])
        if "update public.hydrants" in query and args[1] in ("low_pressure", "no_access"):
            raise asyncpg.InvalidTextRepresentationError(
                f'invalid input value for enum hydrant_status: "{args[1]}"'
            )
        if "select layer_type::text" in query:
            return {
                "layer_type": "bodies_of_water", "operation": "update",
                "target_id": uuid4(), "proposed_data": json.dumps({"is_active": False}),
                "status": "pending",
            }
        if "set status = 'approved'" in query:
            self.approved = True
        return await super().fetchrow(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        if "update public.bodies_of_water" in query and "is_active" in query:
            raise _no_column()
        return "UPDATE 1"


@contextmanager
def _client_for(database: Any) -> Iterator[TestClient]:
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _system_admin() -> None:
    admin = AuthenticatedUser(id=uuid4(), role="admin", full_name="System Administrator")
    app.dependency_overrides[get_current_user] = lambda: admin


def test_water_is_on_every_map_before_its_migration() -> None:
    with _client_for(_BeforeMigration()) as client:
        _as("general_user")
        response = client.get("/map/bodies-of-water")
        one = client.get(f"/map/bodies-of-water/{uuid4()}")
    assert response.status_code == 200, response.text
    (water,) = response.json()
    assert (water["name"], water["is_active"]) == ("Tripa de Gallina", True)
    assert one.status_code == 200, one.text


def test_a_new_status_waits_for_its_migration_the_old_ones_do_not() -> None:
    with _client_for(_BeforeMigration()) as client:
        _as("response_team", "bfp")
        waits = client.post(
            f"/map/hydrants/{uuid4()}/ground-truth", json={"status": "low_pressure"}
        )
        saved = client.post(
            f"/map/hydrants/{uuid4()}/ground-truth", json={"status": "non_operational"}
        )
    assert waits.status_code == 409
    assert waits.json()["error"] == "migration_pending"
    assert saved.status_code == 200, saved.text


def test_switching_water_off_waits_for_its_migration_other_edits_do_not() -> None:
    with _client_for(_BeforeMigration()) as client:
        _system_admin()
        off = client.patch(f"/map/bodies-of-water/{uuid4()}", json={"is_active": False})
        renamed = client.patch(
            f"/map/bodies-of-water/{uuid4()}",
            json={"name": "Estero de Tripa de Gallina", "is_active": True},
        )
    assert off.status_code == 409
    assert off.json()["error"] == "migration_pending"
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Estero de Tripa de Gallina"
    assert renamed.json()["is_active"] is True


def test_approving_a_switch_off_before_its_migration_leaves_it_pending() -> None:
    db = _BeforeMigration()
    with _client_for(db) as client:
        _system_admin()
        response = client.post(f"/map-layer-requests/{uuid4()}/approve", json={})
    assert response.status_code == 409
    assert response.json()["error"] == "migration_pending"
    assert db.approved is False
