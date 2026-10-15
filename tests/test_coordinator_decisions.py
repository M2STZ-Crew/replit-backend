"""What the coordinator app's Accept sheet and "My decisions" rely on (hermetic).

What these pin:
- "I am going too" on an Accept names the unit: the response row carries it,
  as does its audit entry, and a blank unit is stored as none;
- a merge and a keep-separate are kept in the audit log, filed where an
  agency-scoped read finds them — a merge against the Area that lives on,
  since the merged one has no reports left.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api.routes import areas as areas_route
from app.api.routes import incidents
from app.schemas.incident import SelfDispatchRequest
from tests.test_v12 import AREA, _Db, _user


class _UnitDb(_Db):
    """The v12 fake, keeping what the response row and its audit entry say."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.vehicles: list[str | None] = []
        self.audit_metadata: list[dict[str, Any]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        if " ".join(query.split()).startswith("insert into public.dispatch_logs"):
            self.vehicles.append(args[4])
        return await super().fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        if " ".join(query.split()).startswith("insert into public.audit_logs"):
            self.audit_metadata.append(json.loads(args[9]))
        return await super().execute(query, *args)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _finish(_db: Any, _id: UUID, event_type: str) -> str:
        return event_type

    monkeypatch.setattr(incidents, "finish_incident_change", _finish)


async def _respond(db: _Db, payload: SelfDispatchRequest) -> None:
    await incidents.self_dispatch(
        AREA, payload, None, _user("sub_admin"), db  # type: ignore[arg-type]
    )


async def test_going_too_records_the_unit_on_the_response() -> None:
    db = _UnitDb("verified")
    await _respond(db, SelfDispatchRequest(vehicle_name="  Tanker 1 "))
    assert db.vehicles == ["Tanker 1"]
    assert db.state.status == "en_route"
    assert db.audit_metadata[-1]["vehicle_name"] == "Tanker 1"


async def test_a_blank_unit_is_none() -> None:
    db = _UnitDb("verified")
    await _respond(db, SelfDispatchRequest(vehicle_name="   "))
    assert db.vehicles == [None]


async def test_responding_without_a_unit_still_works() -> None:
    db = _UnitDb("verified")
    await _respond(db, SelfDispatchRequest())
    assert db.vehicles == [None]


# --------------------------------------------------------------------------- #
# Overlap decisions
# --------------------------------------------------------------------------- #
class _OverlapDb:
    def __init__(self, keep: UUID, drop: UUID) -> None:
        self.keep, self.drop = keep, drop
        self.audits: list[tuple[str, UUID | None, UUID | None, dict[str, Any]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if q.startswith("select area_a_id, area_b_id, decision, expires_at"):
            return {
                "area_a_id": self.keep,
                "area_b_id": self.drop,
                "decision": None,
                "expires_at": datetime.now(UTC) + timedelta(seconds=60),
            }
        if "as kept" in q:
            return {"kept": "Area 7.1", "merged": "Area 7.3"}
        if q.startswith("update public.area_overlaps set decision = 'keep_separate'"):
            return {"area_a_id": self.keep, "area_b_id": self.drop}
        raise AssertionError(f"unexpected fetchrow: {q[:90]}")

    async def fetchval(self, *_a: Any) -> str:
        return "reported"

    async def execute(self, query: str, *args: Any) -> str:
        if " ".join(query.split()).startswith("insert into public.audit_logs"):
            self.audits.append((args[3], args[5], args[6], json.loads(args[9])))
        return "UPDATE 1"


@pytest.fixture
def overlap(monkeypatch: pytest.MonkeyPatch) -> _OverlapDb:
    async def _noop(*_a: Any) -> None:
        return None

    monkeypatch.setattr(areas_route, "recompute_area", _noop)
    monkeypatch.setattr(areas_route, "publish_area_change", _noop)
    return _OverlapDb(uuid4(), uuid4())


async def test_a_merge_is_kept_against_the_area_that_lives_on(overlap: _OverlapDb) -> None:
    await areas_route.merge_areas(
        uuid4(), None, _user("sub_admin"), overlap  # type: ignore[arg-type]
    )
    [(action, entity_id, area_id, meta)] = overlap.audits
    assert action == "area.merge"
    assert entity_id == overlap.drop
    assert area_id == overlap.keep
    assert meta["merged_designation"] == "Area 7.3"
    assert meta["kept_designation"] == "Area 7.1"


async def test_keeping_them_separate_is_kept_too(overlap: _OverlapDb) -> None:
    await areas_route.keep_areas_separate(
        uuid4(), None, _user("sub_admin"), overlap  # type: ignore[arg-type]
    )
    [(action, _entity, area_id, meta)] = overlap.audits
    assert action == "area.keep_separate"
    assert area_id == overlap.drop
    assert meta["other_area_id"] == str(overlap.keep)
