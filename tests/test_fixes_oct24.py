"""Fixes from the 24 Oct 2026 pilot run (hermetic).

What these pin:
- a fire alerts only the neighbours whose last known location is within
  150 m of it (PRD v13/v14 §4.2), not the 300 m the server used before;
- an alarm request BFP has not answered can be cancelled, and any it did not
  approve deleted, by whoever asked, an Admin of their organisation or the
  system Admin — nobody else; an approved one stays as the record;
- a risk zone carries the circle the Admin sets, 150 m until then.

Routes are called directly against small in-memory fakes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from app.api.routes import alarm_requests, map_layers_admin
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.schemas.alarm import AlarmReviewRequest
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import RiskZoneCreate, RiskZoneResponse, RiskZoneUpdate
from app.services.audit import match_audit_rule
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


class _RequestDb:
    """One alarm request, asked by ``asker`` of ``asker_org``."""

    def __init__(
        self, asker: UUID, asker_org: UUID | None, status: str = "pending", *,
        enum_ready: bool = True,
    ) -> None:
        self.row: dict[str, Any] | None = {
            "status": status, "requested_by": asker, "requester_org": asker_org,
        }
        self.enum_ready = enum_ready
        self.writes: list[str] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if query.lstrip().startswith("select"):
            return self.row
        self.writes.append(query)
        if not self.enum_ready:
            raise asyncpg.InvalidTextRepresentationError(
                'invalid input value for enum request_status: "cancelled"'
            )
        if self.row is None or self.row["status"] != "pending":
            return None
        self.row["status"] = "cancelled"
        return {
            "id": args[0], "area_id": uuid4(), "requested_by": self.row["requested_by"],
            "requested_alarm_level": "second_alarm", "justification": None,
            "status": "cancelled", "reviewed_by": args[1], "reviewed_at": None,
            "review_notes": args[2], "executed_at": None,
            "created_at": "2026-10-18T09:00:00Z", "updated_at": "2026-10-24T09:00:00Z",
        }

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.writes.append(query)
        if self.row is None or self.row["status"] == "approved":
            return None
        self.row = None
        return args[0]


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


async def test_a_pending_request_is_cancelled() -> None:
    asker = _coordinator()
    db = _RequestDb(asker.id, FIRE_ORG)
    got = await alarm_requests.cancel_alarm_request(
        uuid4(), AlarmReviewRequest(notes="Fire is under control"), asker, db  # type: ignore[arg-type]
    )
    assert got.status == "cancelled"
    assert got.reviewed_by == asker.id
    assert "status = 'pending'" in db.writes[0], "never over an answer"


async def test_an_answered_request_cannot_be_cancelled() -> None:
    asker = _coordinator()
    with pytest.raises(ConflictError):
        await alarm_requests.cancel_alarm_request(
            uuid4(), AlarmReviewRequest(), asker, _RequestDb(asker.id, FIRE_ORG, "rejected")  # type: ignore[arg-type]
        )


async def test_someone_else_cannot_cancel_or_delete() -> None:
    db = _RequestDb(uuid4(), FIRE_ORG)
    with pytest.raises(ForbiddenError):
        await alarm_requests.cancel_alarm_request(
            uuid4(), AlarmReviewRequest(), _org_admin(OTHER_ORG), db  # type: ignore[arg-type]
        )
    with pytest.raises(ForbiddenError):
        await alarm_requests.delete_alarm_request(uuid4(), _org_admin(OTHER_ORG), db)  # type: ignore[arg-type]
    assert db.writes == []


async def test_cancel_before_the_migration_says_to_delete_instead() -> None:
    asker = _coordinator()
    with pytest.raises(ConflictError) as exc:
        await alarm_requests.cancel_alarm_request(
            uuid4(), AlarmReviewRequest(), asker,
            _RequestDb(asker.id, FIRE_ORG, enum_ready=False),  # type: ignore[arg-type]
        )
    assert "Delete the request" in exc.value.message


@pytest.mark.parametrize("status", ["pending", "rejected", "cancelled"])
async def test_a_request_bfp_did_not_approve_can_be_deleted(status: str) -> None:
    asker = _coordinator()
    db = _RequestDb(asker.id, FIRE_ORG, status)
    resp = await alarm_requests.delete_alarm_request(uuid4(), _org_admin(), db)  # type: ignore[arg-type]
    assert resp.status_code == 204
    assert db.row is None
    assert "status <> 'approved'" in db.writes[0], "never an approval, even in a race"


async def test_an_approved_request_stays() -> None:
    asker = _coordinator()
    db = _RequestDb(asker.id, FIRE_ORG, "approved")
    with pytest.raises(ConflictError):
        await alarm_requests.delete_alarm_request(uuid4(), _system_admin(), db)  # type: ignore[arg-type]
    assert db.row is not None and db.writes == []


async def test_a_missing_request_is_not_found() -> None:
    db = _RequestDb(uuid4(), FIRE_ORG)
    db.row = None
    with pytest.raises(NotFoundError):
        await alarm_requests.delete_alarm_request(uuid4(), _system_admin(), db)  # type: ignore[arg-type]


def test_cancel_and_delete_are_audited() -> None:
    rid = uuid4()
    assert match_audit_rule("POST", f"/alarm-requests/{rid}/cancel") == (
        "alarm.cancel", "alarm_request", rid, False,
    )
    assert match_audit_rule("DELETE", f"/alarm-requests/{rid}") == (
        "alarm.delete", "alarm_request", rid, False,
    )


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
