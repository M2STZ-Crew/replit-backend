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


async def test_only_neighbours_within_150_m_are_alerted() -> None:
    db = _NeighbourQuery()
    alerted = await neighborhood.notify_area_neighbors(
        db,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        uuid4(),
        14.5,
        121.0,
    )
    assert alerted == 0
    assert neighborhood.NEIGHBORHOOD_RADIUS_M == 150
    assert "ST_DWithin" in db.query and "$3" in db.query
    assert db.args[2] == 150, "the radius the query is given"


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
