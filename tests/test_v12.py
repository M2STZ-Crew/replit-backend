"""v12: verifying and responding are separate acts, open to more people (hermetic).

What these pin (Master Context v12 Section 2.5):
- verify moves reported -> verified and sends nobody; responders may verify
  now, not only a captain; citizens never can;
- respond is open to responders and to Fire Volunteer / BFP coordinators, only
  once verified; the first moves verified -> en_route ("On the way"), later
  ones join without moving it; nobody responds to the same fire twice, even in
  a race the pre-check misses;
- a coordinator may reject until someone is on scene, and a reject releases
  anyone already responding; observers may not respond;
- whoever is responding may stream their location, coordinators included.

Routes are called directly against an in-memory database that honours
transaction rollback and the partial unique index on active responses.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.api.routes import incidents
from app.core.exceptions import ConflictError, ForbiddenError
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import (
    IncidentRejectRequest,
    ResponderLocationCreate,
    SelfDispatchRequest,
)
from app.services.incident import ALLOWED_TRANSITIONS, assert_transition

AREA = uuid4()


def _user(role: str, agency: str | None = "fire_volunteer") -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency)


class _State:
    def __init__(self, status: str) -> None:
        self.status = status
        self.verified_by: UUID | None = None
        self.acceptances: list[dict[str, Any]] = []
        self.dispatches: list[dict[str, Any]] = []
        self.audits: list[str] = []


class _Db:
    """The incident routes' SQL, answered from memory."""

    def __init__(self, status: str) -> None:
        self.state = _State(status)
        # Simulate a same-person race the pre-check cannot see: the insert
        # meets the partial unique index instead.
        self.blind_precheck = False

    # -- connection surface -------------------------------------------------
    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = copy.deepcopy(self.state)
        try:
            yield
        except BaseException:
            self.state = snapshot
            raise

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        s = self.state
        if q.startswith("select status::text from public.areas where id = $1"):
            return s.status
        if "from public.area_reports ar" in q and "selected_agencies" in q:
            return True  # visible to the caller's agency
        if q.startswith("select id from public.dispatch_logs"):
            if self.blind_precheck:
                return None
            for d in s.dispatches:
                if d["responder_id"] == args[1] and d["status"] == "active":
                    return d["id"]
            return None
        if "from public.area_acceptances where area_id = $1 and user_id = $2" in q:
            return any(a["user_id"] == args[1] for a in s.acceptances)
        if "from public.area_acceptances where area_id = $1 and is_first" in q:
            return any(a["is_first"] for a in s.acceptances)
        if q.startswith("insert into public.dispatch_logs"):
            if any(
                d["responder_id"] == args[1] and d["status"] == "active"
                for d in s.dispatches
            ):
                raise asyncpg.UniqueViolationError("dispatch_logs_active_uniq")
            d = {"id": uuid4(), "responder_id": args[1], "status": "active"}
            s.dispatches.append(d)
            return d["id"]
        raise AssertionError(f"unexpected fetchval: {q[:100]}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        s = self.state
        if q.startswith("update public.dispatch_logs set status = 'withdrawn'"):
            out = []
            for d in s.dispatches:
                if d["status"] == "active":
                    d["status"] = "withdrawn"
                    out.append({"id": d["id"]})
            return out
        if q.startswith("update public.dispatch_logs set status = 'completed'"):
            return []
        raise AssertionError(f"unexpected fetch: {q[:100]}")

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        s = self.state
        if q.startswith("update public.areas set status = 'verified'"):
            assert_transition(s.status, "verified")
            s.status, s.verified_by = "verified", args[1]
        elif q.startswith("update public.areas set status = 'en_route'"):
            assert_transition(s.status, "en_route")
            s.status = "en_route"
        elif q.startswith("update public.areas set status = 'rejected'"):
            assert_transition(s.status, "rejected")
            s.status = "rejected"
        elif q.startswith("insert into public.area_acceptances"):
            s.acceptances.append({"user_id": args[1], "is_first": args[4]})
        elif q.startswith("insert into public.audit_logs"):
            s.audits.append(str(args[3]))
        else:
            raise AssertionError(f"unexpected execute: {q[:100]}")
        return "OK"


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _finish(_db: Any, _id: UUID, event_type: str) -> str:
        seen.append(event_type)
        return event_type

    monkeypatch.setattr(incidents, "finish_incident_change", _finish)
    return seen


async def _verify(db: _Db, user: AuthenticatedUser) -> Any:
    return await incidents.accept_incident(AREA, None, user, db)  # type: ignore[arg-type]


async def _respond(db: _Db, user: AuthenticatedUser) -> Any:
    return await incidents.self_dispatch(
        AREA, SelfDispatchRequest(), None, user, db  # type: ignore[arg-type]
    )


async def _reject(db: _Db, user: AuthenticatedUser) -> Any:
    return await incidents.reject_incident(
        AREA, IncidentRejectRequest(reason="misclicked verify"), None, user, db  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Verify
# --------------------------------------------------------------------------- #
async def test_verifying_marks_it_real_and_sends_nobody(events: list[str]) -> None:
    db = _Db("reported")
    captain = _user("sub_admin")
    await _verify(db, captain)
    assert db.state.status == "verified", "not en_route: nobody has said they are going"
    assert db.state.verified_by == captain.id
    assert db.state.dispatches == []
    assert "incident.verify" in db.state.audits
    assert events == ["incident_verified"]


async def test_a_responder_may_verify_when_the_captain_is_away(events: list[str]) -> None:
    db = _Db("reported")
    await _verify(db, _user("response_team"))
    assert db.state.status == "verified"


async def test_a_citizen_may_not_verify(events: list[str]) -> None:
    with pytest.raises(ForbiddenError):
        await _verify(_Db("reported"), _user("general_user", None))


async def test_a_responder_finding_it_verified_is_told_to_respond(
    events: list[str],
) -> None:
    db = _Db("reported")
    await _verify(db, _user("sub_admin"))
    with pytest.raises(ConflictError) as err:
        await _verify(db, _user("response_team"))
    assert "respond" in err.value.message


async def test_a_second_captain_verifying_records_participation(events: list[str]) -> None:
    db = _Db("reported")
    await _verify(db, _user("sub_admin"))
    await _verify(db, _user("sub_admin", "bfp"))
    assert db.state.status == "verified"
    assert [a["is_first"] for a in db.state.acceptances] == [True, False]
    assert events == ["incident_verified", "incident_accepted"]


# --------------------------------------------------------------------------- #
# Respond
# --------------------------------------------------------------------------- #
async def test_nobody_responds_before_it_is_verified(events: list[str]) -> None:
    with pytest.raises(ConflictError) as err:
        await _respond(_Db("reported"), _user("response_team"))
    assert "Verify" in err.value.message


async def test_the_first_to_respond_puts_it_on_the_way(events: list[str]) -> None:
    db = _Db("verified")
    await _respond(db, _user("response_team"))
    assert db.state.status == "en_route"
    assert "incident.en_route" in db.state.audits
    assert events == ["incident_en_route"], "the reporter's 'On the way' push"


async def test_later_responders_join_without_moving_it(events: list[str]) -> None:
    db = _Db("verified")
    await _respond(db, _user("response_team"))
    await _respond(db, _user("response_team"))
    assert db.state.status == "en_route"
    assert len([d for d in db.state.dispatches if d["status"] == "active"]) == 2
    assert events == ["incident_en_route", "responder_dispatched"]


@pytest.mark.parametrize("agency", ["fire_volunteer", "bfp"])
async def test_any_coordinator_may_respond(agency: str, events: list[str]) -> None:
    db = _Db("verified")
    await _respond(db, _user("sub_admin", agency))
    assert db.state.status == "en_route"


@pytest.mark.parametrize(
    "user",
    [_user("sub_admin", "police"), _user("admin", None), _user("general_user", None)],
    ids=["observer", "admin", "citizen"],
)
async def test_observers_admin_and_citizens_do_not_respond(
    user: AuthenticatedUser, events: list[str]
) -> None:
    with pytest.raises(ForbiddenError):
        await _respond(_Db("verified"), user)


async def test_nobody_responds_to_the_same_fire_twice(events: list[str]) -> None:
    db = _Db("verified")
    me = _user("response_team")
    await _respond(db, me)
    with pytest.raises(ConflictError):
        await _respond(db, me)
    assert len(db.state.dispatches) == 1


async def test_a_race_the_precheck_misses_is_still_a_409(events: list[str]) -> None:
    """Two taps at once: the database's unique index refuses the second, cleanly."""
    db = _Db("verified")
    me = _user("response_team")
    await _respond(db, me)
    db.blind_precheck = True
    with pytest.raises(ConflictError) as err:
        await _respond(db, me)
    assert "already responding" in err.value.message
    assert len(db.state.dispatches) == 1, "the failed insert left nothing behind"


# --------------------------------------------------------------------------- #
# Reject
# --------------------------------------------------------------------------- #
async def test_a_mistaken_verify_can_be_rejected(events: list[str]) -> None:
    db = _Db("verified")
    await _reject(db, _user("sub_admin"))
    assert db.state.status == "rejected"


async def test_rejecting_while_on_the_way_releases_the_responders(
    events: list[str],
) -> None:
    db = _Db("verified")
    await _respond(db, _user("response_team"))
    await _respond(db, _user("sub_admin", "bfp"))
    await _reject(db, _user("sub_admin"))
    assert db.state.status == "rejected"
    assert {d["status"] for d in db.state.dispatches} == {"withdrawn"}


async def test_once_on_scene_it_is_fire_out_not_reject() -> None:
    assert "rejected" not in ALLOWED_TRANSITIONS["arrived"]
    assert "rejected" in ALLOWED_TRANSITIONS["en_route"]


@pytest.mark.parametrize("role", ["response_team", "general_user"])
async def test_only_coordinators_reject(role: str, events: list[str]) -> None:
    with pytest.raises(ForbiddenError):
        await _reject(_Db("verified"), _user(role))


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
async def test_a_coordinator_who_responds_may_stream_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[UUID] = []

    async def _record(_db: Any, _area: UUID, who: UUID, _payload: Any) -> bool:
        recorded.append(who)
        return True

    async def _quiet(*_a: Any, **_k: Any) -> Any:
        return False

    monkeypatch.setattr(incidents, "record_responder_location", _record)
    monkeypatch.setattr(incidents, "broadcast_responder_location", _quiet)
    monkeypatch.setattr(incidents, "after_responder_fix", _quiet)
    captain = _user("sub_admin", "bfp")
    fix = ResponderLocationCreate(lat=14.54, lng=121.0, captured_at=datetime.now(UTC))
    await incidents.post_responder_location(AREA, fix, None, captain, object())  # type: ignore[arg-type]
    assert recorded == [captain.id]


async def test_an_observer_may_not_stream_location() -> None:
    fix = ResponderLocationCreate(lat=14.54, lng=121.0, captured_at=datetime.now(UTC))
    with pytest.raises(ForbiddenError):
        await incidents.post_responder_location(
            AREA, fix, None, _user("sub_admin", "police"), object()  # type: ignore[arg-type]
        )
