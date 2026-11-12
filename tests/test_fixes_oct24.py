"""Fixes from the 24 Oct 2026 pilot run (hermetic).

What these pin:
- a fire alerts only the neighbours whose last known location is within
  150 m of it (PRD v13/v14 §4.2), not the 300 m the server used before;
- who may take back an alarm request (the routes themselves are pinned in
  tests/test_alarm_escalation.py);
- a risk zone carries the circle the Admin sets, 150 m until then.

Routes are called directly against small in-memory fakes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.api.routes import alarm_requests, map_layers_admin
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import RiskZoneCreate, RiskZoneResponse, RiskZoneUpdate
from app.workers import neighborhood

FIRE_ORG = uuid4()
OTHER_ORG = uuid4()


# --------------------------------------------------------------------------- #
# 150 m
# --------------------------------------------------------------------------- #
class _NeighbourQuery:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] = ()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "alerted_before" in query:
            self.query = query
            self.args = args
        return []


async def test_only_neighbours_within_100_m_are_alerted() -> None:
    """100 m since 12 Nov 2026 (\"100m corroboration\"); it was 150 m."""
    db = _NeighbourQuery()
    alerted = await neighborhood.notify_area_neighbors(
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        uuid4(),
        14.5,
        121.0,
    )
    assert alerted == 0
    assert neighborhood.NEIGHBORHOOD_RADIUS_M == 100
    assert "ST_DWithin" in db.query and "$3" in db.query
    assert db.args[2] == 100, "the radius the query is given"


async def test_only_a_location_reported_in_the_last_30_minutes_counts() -> None:
    """A location the phone sent hours ago is where they were, not where they
    are: it no longer puts them inside the 150 m (5 Nov 2026, issue list 2.2)."""
    db = _NeighbourQuery()
    await neighborhood.notify_area_neighbors(
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        uuid4(),
        14.5,
        121.0,
    )
    assert "u.location_updated_at > now() - make_interval(mins => $4::int)" in db.query
    assert db.args[3] == 30, "the default window the query is given"


# --------------------------------------------------------------------------- #
# Alarm requests: cancel and delete
# --------------------------------------------------------------------------- #
def _coordinator(org: UUID = FIRE_ORG) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type="fire_volunteer", primary_org_id=org
    )


def _org_admin(
    org: UUID = FIRE_ORG, agency: str = "fire_volunteer", *, active: bool = True
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        role="admin",
        full_name="Hercules Admin",
        primary_org_id=org,
        org_name="Hercules Fire & Rescue",
        org_agency_type=agency,
        org_is_active=active,
    )


def _system_admin() -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="admin", full_name="System Administrator")


def test_who_may_withdraw_a_request() -> None:
    asker = _coordinator()
    may = alarm_requests._may_withdraw
    assert may(asker, asker.id, FIRE_ORG), "whoever asked"
    assert may(_org_admin(), asker.id, FIRE_ORG), "an Admin of their organisation"
    assert may(_system_admin(), asker.id, FIRE_ORG), "the system Admin"
    assert not may(_org_admin(OTHER_ORG), asker.id, FIRE_ORG), "another organisation"
    assert not may(_org_admin(active=False), asker.id, FIRE_ORG), "a turned-off one"
    assert not may(_coordinator(), asker.id, FIRE_ORG), "another Coordinator"
    assert not may(_org_admin(), asker.id, None), "an asker with no organisation"



# --------------------------------------------------------------------------- #
# Risk zone radius
# --------------------------------------------------------------------------- #
def test_a_risk_zone_starts_at_150_m_and_stays_within_bounds() -> None:
    zone = RiskZoneCreate(barangay="76", centroid_lat=14.5, centroid_lng=121.0)
    assert zone.radius_m == 150
    assert RiskZoneUpdate(radius_m=400).radius_m == 400
    for bad in (5, 6000):
        with pytest.raises(ValidationError):
            RiskZoneCreate(barangay="76", centroid_lat=14.5, centroid_lng=121.0, radius_m=bad)
        with pytest.raises(ValidationError):
            RiskZoneUpdate(radius_m=bad)


async def test_a_new_risk_zone_is_saved_with_its_radius() -> None:
    class _Db:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            self.query, self.args = query, args
            return {
                "id": uuid4(), "barangay": "76", "name": None, "risk_level": "high",
                "description": None, "centroid_lat": 14.5, "centroid_lng": 121.0,
                "radius_m": args[6], "area_geojson": None,
                "created_at": "2026-10-24T09:00:00Z", "updated_at": "2026-10-24T09:00:00Z",
            }

    db = _Db()
    got = await map_layers_admin.create_risk_zone(
        RiskZoneCreate(
            barangay="76", risk_level="high", centroid_lat=14.5, centroid_lng=121.0,
            radius_m=320,
        ),
        _system_admin(),
        db,  # type: ignore[arg-type]
    )
    assert "radius_m" in db.query
    assert got.radius_m == 320
    assert isinstance(got, RiskZoneResponse)


# --------------------------------------------------------------------------- #
# A reported location carries its time (5 Nov 2026, issue list 2.2)
# --------------------------------------------------------------------------- #
class _LocationDb:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "UPDATE 1"


def test_reporting_a_location_stamps_when() -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user, get_database
    from app.main import app
    from app.schemas.auth import AuthenticatedUser

    db = _LocationDb()
    # Past the phone gate, as every resident who can report is.
    user = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/auth/me/location", json={"latitude": 14.54, "longitude": 121.0}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204
    (query, args), = db.executed
    assert "location_updated_at = now()" in query
    assert args == (user.id, 14.54, 121.0)
