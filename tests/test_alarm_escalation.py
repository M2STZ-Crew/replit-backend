"""Alarm escalation, Fire Volunteer to BFP, end to end (hermetic; 27 Oct 2026).

What these pin, against an in-memory database that honours transactions:

- asking: only those who may; the level must raise the Area's alarm and the
  Area must be live; the same ask again (a double tap, a retry after a lost
  reply) returns the waiting request without a second row, push or event; a
  different level replaces the asker's waiting request;
- delivery: the request is stored before anyone is told; BFP Coordinators get
  a push naming the request and organisation; every open BFP queue and the
  Area's screens hear it on ``agency:bfp`` and ``incident:<area>``;
- answering: only BFP; a request answered once cannot be answered again; a
  level that would not raise the alarm, or an Area that has ended, is refused
  and leaves the request waiting; setting it moves the Area's level; the asker
  hears the answer;
- withdrawal: cancel and delete, for the asker, their organisation's Admin or
  the system Admin only; an approved request stays;
- the record: every act writes its own audit row in the same transaction, and
  the best-effort middleware no longer records them twice.
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
from fastapi import Response
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import alarm_requests as ar
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.realtime import events
from app.schemas.alarm import AlarmRequestCreate, AlarmRequestResponse, AlarmReviewRequest
from app.schemas.auth import AuthenticatedUser
from app.services import incident_notify
from app.services.audit import match_audit_rule

FIRE_ORG = uuid4()
OTHER_ORG = uuid4()


def _fv_coordinator(org: UUID = FIRE_ORG) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type="fire_volunteer", primary_org_id=org,
        full_name="R. Alonzo",
    )


def _bfp_coordinator() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type="bfp", full_name="C. Reyes"
    )


def _police_coordinator() -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="police")


def _org_admin(org: UUID = FIRE_ORG, *, active: bool = True) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name="Hercules Admin", primary_org_id=org,
        org_name="Hercules Fire & Rescue", org_agency_type="fire_volunteer",
        org_is_active=active,
    )


def _system_admin() -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="admin", full_name="System Administrator")


# --------------------------------------------------------------------------- #
# An in-memory database for the alarm routes
# --------------------------------------------------------------------------- #
class _Db:
    """Areas, users, organisations, alarm requests and the audit log."""

    def __init__(self) -> None:
        self.area = uuid4()
        self.areas: dict[UUID, dict[str, Any]] = {
            self.area: {"status": "en_route", "alarm_level": None, "designation": "1.2",
                        "lat": 14.5378, "lng": 121.0014},
        }
        self.users: dict[UUID, dict[str, Any]] = {}
        self.orgs: dict[UUID, str] = {FIRE_ORG: "Hercules Fire & Rescue"}
        self.requests: dict[UUID, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        # A database from before migration 20261024090000 has no 'cancelled'.
        self.no_cancelled = False

    def add(self, user: AuthenticatedUser) -> AuthenticatedUser:
        self.users[user.id] = {"full_name": user.full_name, "org": user.primary_org_id}
        return user

    def seed(self, asker: AuthenticatedUser, level: str, status: str = "pending") -> UUID:
        rid = uuid4()
        now = datetime.now(UTC)
        self.requests[rid] = {
            "id": rid, "area_id": self.area, "requested_by": asker.id, "level": level,
            "justification": None, "status": status, "reviewed_by": None,
            "reviewed_at": None, "review_notes": None, "executed_at": None,
            "created_at": now, "updated_at": now,
        }
        return rid

    # -- transactions ------------------------------------------------------ #
    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        saved = copy.deepcopy((self.areas, self.requests, self.audit))
        try:
            yield
        except BaseException:
            self.areas, self.requests, self.audit = saved
            raise

    # -- queries ------------------------------------------------------------ #
    def _detail(self, rid: UUID) -> dict[str, Any] | None:
        r = self.requests.get(rid)
        if r is None:
            return None
        area = self.areas.get(r["area_id"], {})
        asker = self.users.get(r["requested_by"], {})
        reviewer = self.users.get(r["reviewed_by"], {}) if r["reviewed_by"] else {}
        return {
            "id": rid, "area_id": r["area_id"], "area_designation": area.get("designation"),
            "area_status": area.get("status"), "area_alarm_level": area.get("alarm_level"),
            "area_centroid_lat": area.get("lat"), "area_centroid_lng": area.get("lng"),
            "requested_by": r["requested_by"], "requested_by_name": asker.get("full_name"),
            "requested_by_organization_id": asker.get("org"),
            "requested_by_organization_name": self.orgs.get(asker.get("org")),
            "requested_alarm_level": r["level"], "justification": r["justification"],
            "status": r["status"], "reviewed_by": r["reviewed_by"],
            "reviewed_by_name": reviewer.get("full_name"), "reviewed_at": r["reviewed_at"],
            "review_notes": r["review_notes"], "executed_at": r["executed_at"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if "pg_advisory_xact_lock" in q:
            return "SELECT 1"
        if q.startswith("insert into public.audit_logs"):
            self.audit.append({"action": args[3], "entity_id": args[5], "area_id": args[6],
                               "before": args[7], "after": args[8]})
            return "INSERT 0 1"
        if "update public.alarm_requests set status = 'cancelled'" in q:
            r = self.requests[args[0]]
            if r["status"] == "pending":
                r.update(status="cancelled", reviewed_by=args[1], review_notes=args[2],
                         reviewed_at=datetime.now(UTC))
            return "UPDATE 1"
        if q.startswith("update public.areas set alarm_level"):
            self.areas[args[0]]["alarm_level"] = args[1]
            return "UPDATE 1"
        if "update public.alarm_requests set status = 'approved'" in q:
            self.requests[args[0]].update(
                status="approved", reviewed_by=args[1], review_notes=args[2],
                reviewed_at=datetime.now(UTC), executed_at=datetime.now(UTC),
            )
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {q[:90]}")

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if "from public.alarm_requests a left join public.areas ar" in q:
            return self._detail(args[0])
        if q.startswith("select status::text as status, alarm_level::text as alarm_level"):
            a = self.areas.get(args[0])
            return None if a is None else {"status": a["status"],
                                           "alarm_level": a["alarm_level"],
                                           "designation": a["designation"]}
        if "requested_alarm_level::text as lvl" in q:
            r = self.requests.get(args[0])
            return None if r is None else {"area_id": r["area_id"], "lvl": r["level"],
                                           "status": r["status"]}
        if "set status = 'rejected'" in q:
            r = self.requests.get(args[0])
            if r is None or r["status"] != "pending":
                return None
            r.update(status="rejected", reviewed_by=args[1], review_notes=args[2],
                     reviewed_at=datetime.now(UTC))
            return {"area_id": r["area_id"]}
        if "set status = 'cancelled'" in q and "returning id" in q:
            if self.no_cancelled:
                raise asyncpg.InvalidTextRepresentationError(
                    'invalid input value for enum request_status: "cancelled"'
                )
            r = self.requests.get(args[0])
            if r is None or r["status"] != "pending":
                return None
            r.update(status="cancelled", reviewed_by=args[1], review_notes=args[2],
                     reviewed_at=datetime.now(UTC))
            return {"id": args[0]}
        if "u.primary_org_id as requester_org" in q:
            r = self.requests.get(args[0])
            if r is None:
                return None
            return {"status": r["status"], "requested_by": r["requested_by"],
                    "area_id": r["area_id"],
                    "requester_org": self.users.get(r["requested_by"], {}).get("org")}
        raise AssertionError(f"unexpected fetchrow: {q[:90]}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        if "from public.alarm_requests where area_id = $1 and requested_by = $2" in q:
            return [{"id": r["id"], "level": r["level"]} for r in self.requests.values()
                    if r["area_id"] == args[0] and r["requested_by"] == args[1]
                    and r["status"] == "pending"]
        if "from public.alarm_requests a left join public.areas ar" in q:
            rows = [self._detail(rid) for rid in self.requests]
            return [r for r in rows if r is not None]
        raise AssertionError(f"unexpected fetch: {q[:90]}")

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        if q.startswith("insert into public.alarm_requests"):
            rid = uuid4()
            now = datetime.now(UTC)
            self.requests[rid] = {
                "id": rid, "area_id": args[0], "requested_by": args[1], "level": args[2],
                "justification": args[3], "status": "pending", "reviewed_by": None,
                "reviewed_at": None, "review_notes": None, "executed_at": None,
                "created_at": now, "updated_at": now,
            }
            return rid
        if q.startswith("delete from public.alarm_requests"):
            r = self.requests.get(args[0])
            if r is None or r["status"] == "approved":
                return None
            del self.requests[args[0]]
            return args[0]
        raise AssertionError(f"unexpected fetchval: {q[:90]}")


class _Told:
    """What reached the outside world: socket events, pushes, the map."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.sockets: list[tuple[str, dict[str, Any]]] = []
        self.bfp: list[dict[str, Any]] = []
        self.answers: list[AlarmRequestResponse] = []


@pytest.fixture
def told(monkeypatch: pytest.MonkeyPatch) -> _Told:
    t = _Told()

    async def announce(detail: dict[str, Any], event: str) -> None:
        t.events.append((event, str(detail["id"])))

    async def bfp(db: Any, area_id: UUID, by: UUID, level: str, **kw: Any) -> int:
        t.bfp.append({"area_id": area_id, "level": level, **kw})
        return 1

    async def answered(db: Any, detail: AlarmRequestResponse) -> int:
        t.answers.append(detail)
        return 1

    async def socket(channel: str, message: dict[str, Any]) -> int:
        t.sockets.append((channel, message))
        return 1

    async def no_map(*_: Any, **__: Any) -> int:
        return 0

    monkeypatch.setattr(ar, "broadcast_alarm_request", announce)
    monkeypatch.setattr(ar, "notify_bfp_alarm_request", bfp)
    monkeypatch.setattr(ar, "notify_alarm_request_answered", answered)
    monkeypatch.setattr(ar.manager, "broadcast", socket)
    monkeypatch.setattr(ar, "publish_area_change", no_map)
    return t


async def _ask(db: _Db, user: AuthenticatedUser, level: str) -> tuple[AlarmRequestResponse, int]:
    response = Response()
    response.status_code = 201
    got = await ar.create_alarm_request(
        AlarmRequestCreate(area_id=db.area, requested_alarm_level=level),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        response,
        user,
        db,  # type: ignore[arg-type]
    )
    return got, response.status_code


# --------------------------------------------------------------------------- #
# Asking
# --------------------------------------------------------------------------- #
async def test_a_request_is_stored_audited_and_sent_to_bfp(told: _Told) -> None:
    db = _Db()
    asker = db.add(_fv_coordinator())
    got, code = await _ask(db, asker, "first_alarm")
    assert code == 201
    assert got.status == "pending" and got.requested_alarm_level == "first_alarm"
    assert got.requested_by_organization_name == "Hercules Fire & Rescue"
    assert got.area_centroid_lat == 14.5378 and got.area_status == "en_route"
    assert [a["action"] for a in db.audit] == ["alarm.request"]
    assert told.events == [("requested", str(got.id))]
    assert told.bfp == [{"area_id": db.area, "level": "first_alarm",
                         "request_id": got.id, "organization": "Hercules Fire & Rescue"}]


async def test_the_same_ask_again_is_the_same_request(told: _Told) -> None:
    """A double tap, or a retry after a lost reply: no second row, push or event."""
    db = _Db()
    asker = db.add(_fv_coordinator())
    first, _ = await _ask(db, asker, "first_alarm")
    again, code = await _ask(db, asker, "first_alarm")
    assert code == 200 and again.id == first.id
    assert len(db.requests) == 1
    assert len(told.bfp) == 1 and len(told.events) == 1
    assert len(db.audit) == 1


async def test_a_new_level_replaces_the_askers_waiting_request(told: _Told) -> None:
    db = _Db()
    asker = db.add(_fv_coordinator())
    first, _ = await _ask(db, asker, "first_alarm")
    second, code = await _ask(db, asker, "second_alarm")
    assert code == 201
    assert db.requests[first.id]["status"] == "cancelled"
    assert db.requests[first.id]["review_notes"] == "Replaced by a request for 2nd alarm."
    assert db.requests[second.id]["status"] == "pending"
    assert told.events[-2:] == [("cancelled", str(first.id)), ("requested", str(second.id))]


async def test_two_askers_each_keep_their_own_request(told: _Told) -> None:
    db = _Db()
    one, two = db.add(_fv_coordinator()), db.add(_fv_coordinator())
    a, _ = await _ask(db, one, "first_alarm")
    b, _ = await _ask(db, two, "first_alarm")
    assert a.id != b.id and len(db.requests) == 2


@pytest.mark.parametrize("current", ["first_alarm", "second_alarm"])
async def test_a_level_that_would_not_raise_the_alarm_is_refused(
    told: _Told, current: str
) -> None:
    db = _Db()
    db.areas[db.area]["alarm_level"] = current
    with pytest.raises(ConflictError) as exc:
        await _ask(db, db.add(_fv_coordinator()), "first_alarm")
    assert "already at" in exc.value.message
    assert db.requests == {} and told.bfp == []


async def test_an_ended_area_takes_no_request(told: _Told) -> None:
    db = _Db()
    db.areas[db.area]["status"] = "fire_out"
    with pytest.raises(ConflictError):
        await _ask(db, db.add(_fv_coordinator()), "first_alarm")


async def test_only_those_who_may_ask_can(told: _Told) -> None:
    db = _Db()
    for user in (_police_coordinator(), _bfp_coordinator()):
        if user.agency_type == "bfp":
            await _ask(db, db.add(user), "first_alarm")  # BFP Coordinators may ask too
            continue
        with pytest.raises(ForbiddenError):
            await _ask(db, db.add(user), "first_alarm")


async def test_a_failed_write_tells_nobody(told: _Told, monkeypatch: pytest.MonkeyPatch) -> None:
    """The request is stored first; if storing fails, no push and no event."""
    db = _Db()

    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(ar, "record_audit", broken)
    with pytest.raises(RuntimeError):
        await _ask(db, db.add(_fv_coordinator()), "first_alarm")
    assert db.requests == {}, "rolled back with the audit row"
    assert told.bfp == [] and told.events == []


# --------------------------------------------------------------------------- #
# Answering
# --------------------------------------------------------------------------- #
async def _execute(db: _Db, user: AuthenticatedUser, rid: UUID) -> AlarmRequestResponse:
    return await ar.execute_alarm_request(
        rid, AlarmReviewRequest(), None, user, db  # type: ignore[arg-type]
    )


async def test_bfp_sets_the_level_and_the_asker_hears(told: _Told) -> None:
    db = _Db()
    asker = db.add(_fv_coordinator())
    rid = db.seed(asker, "second_alarm")
    bfp = db.add(_bfp_coordinator())
    got = await _execute(db, bfp, rid)
    assert got.status == "approved" and got.reviewed_by_name == "C. Reyes"
    assert db.areas[db.area]["alarm_level"] == "second_alarm"
    audit = db.audit[-1]
    assert audit["action"] == "alarm.execute"
    assert '"alarm_level": null' in audit["before"] and "second_alarm" in audit["after"]
    assert (f"incident:{db.area}", {"type": "alarm_raised", "area_id": str(db.area),
            "alarm_level": "second_alarm", "set_by": str(bfp.id)}) in told.sockets
    assert ("approved", str(rid)) in told.events
    assert [a.status for a in told.answers] == ["approved"]


async def test_a_request_answered_once_cannot_be_answered_again(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm")
    await _execute(db, db.add(_bfp_coordinator()), rid)
    with pytest.raises(ConflictError):
        await _execute(db, db.add(_bfp_coordinator()), rid)
    assert len([a for a in db.audit if a["action"] == "alarm.execute"]) == 1


async def test_a_stale_request_does_not_lower_the_alarm(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm")
    db.areas[db.area]["alarm_level"] = "third_alarm"
    with pytest.raises(ConflictError) as exc:
        await _execute(db, db.add(_bfp_coordinator()), rid)
    assert "Decline this request instead" in exc.value.message
    assert db.areas[db.area]["alarm_level"] == "third_alarm"
    assert db.requests[rid]["status"] == "pending", "still there to decline"


async def test_an_ended_area_keeps_its_level(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm")
    db.areas[db.area]["status"] = "post_incident_report"
    with pytest.raises(ConflictError):
        await _execute(db, db.add(_bfp_coordinator()), rid)
    assert db.areas[db.area]["alarm_level"] is None


async def test_bfp_declines_and_the_asker_hears(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "third_alarm")
    got = await ar.reject_alarm_request(
        rid, AlarmReviewRequest(notes="Contained at 1st alarm"), None,  # type: ignore[arg-type]
        db.add(_bfp_coordinator()), db,  # type: ignore[arg-type]
    )
    assert got.status == "rejected" and got.review_notes == "Contained at 1st alarm"
    assert db.audit[-1]["action"] == "alarm.reject"
    assert ("rejected", str(rid)) in told.events
    assert [a.status for a in told.answers] == ["rejected"]
    with pytest.raises(NotFoundError):
        await ar.reject_alarm_request(
            rid, AlarmReviewRequest(), None, db.add(_bfp_coordinator()), db,  # type: ignore[arg-type]
        )


async def test_only_bfp_answers(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm")
    for user in (_fv_coordinator(), _police_coordinator(), _org_admin(), _system_admin()):
        with pytest.raises(ForbiddenError):
            await _execute(db, db.add(user), rid)
        with pytest.raises(ForbiddenError):
            await ar.reject_alarm_request(
                rid, AlarmReviewRequest(), None, user, db  # type: ignore[arg-type]
            )
    assert db.requests[rid]["status"] == "pending"


# --------------------------------------------------------------------------- #
# Taking a request back
# --------------------------------------------------------------------------- #
async def test_the_asker_cancels_a_waiting_request(told: _Told) -> None:
    db = _Db()
    asker = db.add(_fv_coordinator())
    rid = db.seed(asker, "first_alarm")
    got = await ar.cancel_alarm_request(
        rid, AlarmReviewRequest(notes="Under control"), None, asker, db  # type: ignore[arg-type]
    )
    assert got.status == "cancelled" and got.reviewed_by == asker.id
    assert db.audit[-1]["action"] == "alarm.cancel"
    assert ("cancelled", str(rid)) in told.events


async def test_cancel_before_the_migration_says_to_delete_instead(told: _Told) -> None:
    db = _Db()
    db.no_cancelled = True
    asker = db.add(_fv_coordinator())
    rid = db.seed(asker, "first_alarm")
    with pytest.raises(ConflictError) as exc:
        await ar.cancel_alarm_request(
            rid, AlarmReviewRequest(), None, asker, db  # type: ignore[arg-type]
        )
    assert "Delete the request" in exc.value.message
    assert db.requests[rid]["status"] == "pending" and db.audit == []


async def test_an_answered_request_cannot_be_cancelled(told: _Told) -> None:
    db = _Db()
    asker = db.add(_fv_coordinator())
    rid = db.seed(asker, "first_alarm", "rejected")
    with pytest.raises(ConflictError):
        await ar.cancel_alarm_request(
            rid, AlarmReviewRequest(), None, asker, db  # type: ignore[arg-type]
        )


async def test_someone_else_cannot_cancel_or_delete(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm")
    stranger = db.add(_org_admin(OTHER_ORG))
    with pytest.raises(ForbiddenError):
        await ar.cancel_alarm_request(
            rid, AlarmReviewRequest(), None, stranger, db  # type: ignore[arg-type]
        )
    with pytest.raises(ForbiddenError):
        await ar.delete_alarm_request(rid, None, stranger, db)  # type: ignore[arg-type]
    assert db.requests[rid]["status"] == "pending" and db.audit == []


@pytest.mark.parametrize("state", ["pending", "rejected", "cancelled"])
async def test_a_request_bfp_did_not_approve_can_be_deleted(told: _Told, state: str) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm", state)
    resp = await ar.delete_alarm_request(rid, None, db.add(_org_admin()), db)  # type: ignore[arg-type]
    assert resp.status_code == 204 and rid not in db.requests
    assert db.audit[-1]["action"] == "alarm.delete"
    assert ("deleted", str(rid)) in told.events


async def test_an_approved_request_stays(told: _Told) -> None:
    db = _Db()
    rid = db.seed(db.add(_fv_coordinator()), "first_alarm", "approved")
    with pytest.raises(ConflictError):
        await ar.delete_alarm_request(rid, None, db.add(_system_admin()), db)  # type: ignore[arg-type]
    assert rid in db.requests and db.audit == []


async def test_a_missing_request_is_not_found(told: _Told) -> None:
    with pytest.raises(NotFoundError):
        await ar.delete_alarm_request(uuid4(), None, _system_admin(), _Db())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# What goes out
# --------------------------------------------------------------------------- #
async def test_an_event_reaches_bfps_feed_and_the_areas_screens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def socket(channel: str, message: dict[str, Any]) -> int:
        sent.append((channel, message))
        return 1

    monkeypatch.setattr(events.manager, "broadcast", socket)
    area = str(uuid4())
    await events.broadcast_alarm_request({"id": "r1", "area_id": area, "status": "pending"},
                                         "requested")
    assert [c for c, _ in sent] == ["agency:bfp", f"incident:{area}"]
    assert sent[0][1]["type"] == "alarm_request" and sent[0][1]["event"] == "requested"


class _PushDb:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return [{"fcm_token": t} for t in self.tokens]

    async def execute(self, *_: Any) -> str:
        return "OK"


@pytest.mark.parametrize(
    ("status", "title"),
    [("approved", "BFP raised the alarm"),
     ("rejected", "BFP declined your alarm request")],
)
async def test_the_asker_is_told_the_answer(
    monkeypatch: pytest.MonkeyPatch, status: str, title: str
) -> None:
    pushed: list[dict[str, Any]] = []
    inbox: list[tuple[Any, ...]] = []

    class _Push:
        async def send_to_tokens(self, **kw: Any) -> Any:
            pushed.append(kw)
            return type("R", (), {"invalid_tokens": []})()

    async def record(*a: Any, **_: Any) -> None:
        inbox.append(a)

    monkeypatch.setattr(incident_notify, "PushService", _Push)
    monkeypatch.setattr(incident_notify, "record_inbox", record)
    now = datetime.now(UTC)
    detail = AlarmRequestResponse(
        id=uuid4(), area_id=uuid4(), area_designation="1.2", requested_by=uuid4(),
        requested_alarm_level="second_alarm", status=status, review_notes="Contained",
        created_at=now, updated_at=now,
    )
    sent = await incident_notify.notify_alarm_request_answered(
        _PushDb(["tok"]), detail  # type: ignore[arg-type]
    )
    assert sent == 1
    assert pushed[0]["title"] == title
    assert pushed[0]["body"].startswith(
        "Area 1.2 is now at 2nd alarm" if status == "approved" else "Area 1.2 stays as it is."
    )
    assert pushed[0]["data"]["type"] == "alarm_request_answered"
    assert pushed[0]["data"]["request_id"] == str(detail.id)
    assert pushed[0]["tag"] == f"alarm-answer-{detail.id}", "a repeat never stacks"
    assert "sound" not in pushed[0], "an answer, not a new fire: the phone's own tone"
    assert inbox and inbox[0][2] == "alarm_request_answered"


async def test_a_waiting_request_tells_the_asker_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    detail = AlarmRequestResponse(
        id=uuid4(), area_id=uuid4(), requested_by=uuid4(),
        requested_alarm_level="first_alarm", status="pending", created_at=now, updated_at=now,
    )
    assert await incident_notify.notify_alarm_request_answered(
        _PushDb(["tok"]), detail  # type: ignore[arg-type]
    ) == 0


class _BfpDb:
    def __init__(self) -> None:
        self.recipients: tuple[str, tuple[Any, ...]] | None = None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return "1.2" if "designation" in query else "R. Alonzo"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "device_tokens" in query:
            return [{"fcm_token": "tok"}]
        self.recipients = (query, args)
        return [{"id": uuid4()}]

    async def execute(self, *_: Any) -> str:
        return "OK"


async def test_bfps_push_names_the_request_and_the_organisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[dict[str, Any]] = []

    class _Push:
        async def send_to_tokens(self, **kw: Any) -> Any:
            pushed.append(kw)
            return type("R", (), {"invalid_tokens": []})()

    async def record(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(incident_notify, "PushService", _Push)
    monkeypatch.setattr(incident_notify, "record_inbox", record)
    rid, asker, db = uuid4(), uuid4(), _BfpDb()
    await incident_notify.notify_bfp_alarm_request(
        db, uuid4(), asker, "first_alarm",  # type: ignore[arg-type]
        request_id=rid, organization="Hercules Fire & Rescue",
    )
    assert pushed[0]["data"]["request_id"] == str(rid)
    assert pushed[0]["sound"] == "fire"
    assert pushed[0]["body"] == (
        "R. Alonzo (Hercules Fire & Rescue) asked for 1st alarm on Area 1.2."
    )
    assert db.recipients is not None
    query, args = db.recipients
    assert "id <> $1" in query and args == (asker,), "a BFP asker is not alerted by their own"


# --------------------------------------------------------------------------- #
# The queue's read
# --------------------------------------------------------------------------- #
class _ListDb:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[Any, ...] = ()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.query, self.args = " ".join(query.split()), args
        return []


async def test_the_queue_reads_waiting_first_and_a_bounded_history() -> None:
    db = _ListDb()
    await ar.list_alarm_requests(
        _bfp_coordinator(), db, None, None, 50  # type: ignore[arg-type]
    )
    assert "order by (a.status = 'pending') desc, a.created_at desc limit $1" in db.query
    assert db.args == (50,)
    area = uuid4()
    await ar.list_alarm_requests(
        _bfp_coordinator(), db, "pending", area, 200  # type: ignore[arg-type]
    )
    assert "a.status = $1::public.request_status and a.area_id = $2" in db.query
    assert db.args == ("pending", area, 200)


async def test_my_requests_can_be_one_areas() -> None:
    db = _ListDb()
    me, area = _fv_coordinator(), uuid4()
    await ar.my_alarm_requests(me, db, area)  # type: ignore[arg-type]
    assert "a.requested_by = $1 and ($2::uuid is null or a.area_id = $2)" in db.query
    assert "order by a.created_at desc" in db.query
    assert db.args == (me.id, area)


def test_an_unknown_status_is_refused_not_a_server_error() -> None:
    db = _ListDb()
    app.dependency_overrides[get_current_user] = _bfp_coordinator
    app.dependency_overrides[get_database] = lambda: db
    try:
        with TestClient(app) as client:
            bad = client.get("/alarm-requests", params={"status": "maybe"})
            good = client.get("/alarm-requests", params={"status": "pending"})
    finally:
        app.dependency_overrides.clear()
    assert bad.status_code == 422, bad.text
    assert good.status_code == 200, good.text
    assert good.json() == []


def test_the_middleware_no_longer_records_them_twice() -> None:
    rid = uuid4()
    for method, path in [
        ("POST", f"/alarm-requests/{rid}/execute"),
        ("POST", f"/alarm-requests/{rid}/reject"),
        ("POST", f"/alarm-requests/{rid}/cancel"),
        ("DELETE", f"/alarm-requests/{rid}"),
    ]:
        assert match_audit_rule(method, path) is None
