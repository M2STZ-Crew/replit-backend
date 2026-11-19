"""v1.12.41: prank and malicious reports, a progressive pause and appeals.

19 Nov 2026: "a false alarm or prank report can be temporarily cannot report
and has a progressive penalty"; "Yes, build it" to the ladder in
app/services/report_strikes.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ConflictError, ReportingPausedError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import report_strikes as rs
from app.services.citizen_copy import strike_message

NOW = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)  # 2:00 PM in Manila
PHONE = "+639171234567"


@pytest.fixture(autouse=True)
def _gates(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "require_citizen_email_verification", False)
    monkeypatch.setattr(settings, "require_citizen_phone_verification", False)
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")


def _row(**kw: Any) -> dict[str, Any]:
    """A report_strikes row; an active 1st step given at NOW unless told otherwise."""
    given = kw.pop("given_at", NOW)
    status = kw.pop("status", "active")
    row: dict[str, Any] = {
        "id": uuid4(),
        "user_id": None,
        "phone_mac": None,
        "report_id": uuid4(),
        "area_id": uuid4(),
        "step": 1,
        "status": status,
        "reason": "The photo was copied from the internet.",
        "serious": False,
        "given_by": uuid4(),
        "given_at": given,
        "checked_by": None,
        "checked_at": None,
        "check_note": None,
        "starts_at": given if status == "active" else None,
        "expires_at": given + rs.LIFETIME if status == "active" else None,
        "lesson_seen_at": None,
        "appeal_text": None,
        "appealed_at": None,
        "appeal_decision": None,
        "appeal_note": None,
        "appeal_decided_by": None,
        "appeal_decided_at": None,
        "overturned_at": None,
    }
    row.update(kw)
    return row


def _strike(**kw: Any) -> rs.Strike:
    return rs.Strike.from_row(_row(**kw))


def _standing(*strikes: rs.Strike, at: datetime = NOW) -> rs.Standing:
    return rs.Standing(now=at, strikes=strikes)


# --------------------------------------------------------------------------- #
# The ladder
# --------------------------------------------------------------------------- #
def test_each_prank_goes_one_step_up_to_the_fourth() -> None:
    counted: list[rs.Strike] = []
    steps = []
    for _ in range(5):
        step = rs.next_step(counted, serious=False)
        steps.append(step)
        counted.append(_strike(step=step))
    assert steps == [1, 2, 3, 4, 4]


def test_a_serious_case_starts_at_the_third_and_the_next_is_the_fourth() -> None:
    assert rs.next_step([], serious=True) == 3
    after_serious = [_strike(step=3)]
    assert rs.next_step(after_serious, serious=False) == 4


def test_the_first_strike_pauses_reporting_for_24_hours() -> None:
    standing = _standing(_strike(step=1))
    assert not standing.can_report
    assert standing.paused_until == NOW + timedelta(hours=24)
    later = _standing(_strike(step=1), at=NOW + timedelta(hours=25))
    assert later.can_report
    assert not later.verify_first  # the 1st step has no verify-first after it


def test_the_second_strike_pauses_7_days_then_30_days_of_verify_first() -> None:
    strike = _strike(step=2)
    during = _standing(strike, at=NOW + timedelta(days=6))
    assert not during.can_report
    after = _standing(strike, at=NOW + timedelta(days=8))
    assert after.can_report and after.verify_first
    assert after.verify_first_until == NOW + timedelta(days=37)
    done = _standing(strike, at=NOW + timedelta(days=38))
    assert done.can_report and not done.verify_first


def test_the_fourth_strike_removes_reporting_until_an_appeal() -> None:
    standing = _standing(_strike(step=4, expires_at=None), at=NOW + timedelta(days=400))
    assert standing.removed and not standing.can_report and standing.verify_first
    assert standing.paused_until is None


def test_a_third_step_awaiting_its_check_pauses_24_hours_and_is_verify_first() -> None:
    strike = _strike(step=3, status="awaiting_confirmation")
    assert _standing(strike).paused_until == NOW + rs.PROVISIONAL_PAUSE
    two_days = _standing(strike, at=NOW + timedelta(days=2))
    assert two_days.can_report and two_days.verify_first
    assert not _standing(strike, at=NOW + timedelta(days=8)).verify_first


def test_overturned_and_expired_strikes_do_not_count() -> None:
    gone = _strike(step=2, status="overturned", overturned_at=NOW)
    old = _strike(step=1, given_at=NOW - timedelta(days=400))
    standing = _standing(gone, old)
    assert standing.counted == ()
    assert standing.step == 0 and standing.can_report
    assert rs.next_step(standing.counted, serious=False) == 1


def test_the_lesson_is_due_once_per_strike() -> None:
    fresh = _strike(step=1)
    assert _standing(fresh).lesson_due == fresh
    seen = _strike(step=1, lesson_seen_at=NOW)
    assert _standing(seen).lesson_due is None


# --------------------------------------------------------------------------- #
# Appeals
# --------------------------------------------------------------------------- #
def test_an_appeal_is_open_for_7_days_and_once() -> None:
    strike = _strike(step=2)
    assert strike.can_appeal(NOW + timedelta(days=6))
    assert not strike.can_appeal(NOW + timedelta(days=8))
    pending = _strike(step=2, appealed_at=NOW + timedelta(days=1))
    assert pending.appeal_state() == "pending"
    assert not pending.can_appeal(NOW + timedelta(days=2))
    upheld = _strike(step=2, appealed_at=NOW, appeal_decision="upheld")
    assert not upheld.can_appeal(NOW + timedelta(days=2))


def test_a_strike_awaiting_its_check_cannot_be_appealed_yet() -> None:
    assert not _strike(step=3, status="awaiting_confirmation").can_appeal(NOW)


def test_the_fourth_step_may_ask_again_once_a_year_after_12_months() -> None:
    strike = _strike(step=4, expires_at=None, appealed_at=NOW, appeal_decision="upheld")
    assert not strike.can_appeal(NOW + timedelta(days=200))
    a_year = NOW + timedelta(days=366)
    assert strike.can_appeal(a_year)
    asked_again = _strike(
        step=4, expires_at=None, appealed_at=a_year, appeal_decision="upheld"
    )
    assert not asked_again.can_appeal(a_year + timedelta(days=30))
    assert asked_again.can_appeal(a_year + timedelta(days=366))


# --------------------------------------------------------------------------- #
# Following the number, not just the account
# --------------------------------------------------------------------------- #
def test_strikes_follow_the_verified_number() -> None:
    mac = rs.phone_mac(PHONE, True)
    assert mac is not None and mac == rs.phone_mac(PHONE, True)
    assert PHONE not in mac  # the number itself is never stored
    assert rs.phone_mac(PHONE, False) is None
    assert rs.phone_mac("+639181112222", True) != mac
    other_account = uuid4()
    strike = _strike(user_id=uuid4(), phone_mac=mac)
    assert strike.belongs_to(other_account, mac)
    assert not strike.belongs_to(other_account, None)


def test_the_console_sees_a_masked_number() -> None:
    assert rs.mask_phone(PHONE) == "+63 9•• ••• 4567"
    assert rs.mask_phone(None) is None


# --------------------------------------------------------------------------- #
# What the resident reads
# --------------------------------------------------------------------------- #
def test_the_resident_reads_until_when_and_911_in_their_language() -> None:
    until = rs.when(NOW + timedelta(hours=24), "en")
    assert until == "20 Nov, 2:00 PM"
    title, body = strike_message(
        "en", "given", step=1, awaiting=False, until=until, can_report=False
    )
    assert title == "Reporting paused until 20 Nov, 2:00 PM"
    assert "911" in body
    tl_title, tl_body = strike_message(
        "tl", "given", step=1, awaiting=False, until=rs.when(NOW, "tl"), can_report=False
    )
    assert "Nob" in tl_title and "911" in tl_body
    removed, removed_body = strike_message(
        "en", "confirmed", step=4, awaiting=False, until="", can_report=False
    )
    assert removed == "You can no longer send reports"
    assert "fire alerts" in removed_body and "911" in removed_body
    _, granted = strike_message(
        "en", "overturned", step=2, awaiting=False, until="", can_report=True
    )
    assert granted == "The strike was removed. You can send reports again."


# --------------------------------------------------------------------------- #
# A fake database, for the service and the routes
# --------------------------------------------------------------------------- #
class _Db:
    """Answers the strike service's queries from plain lists."""

    def __init__(self) -> None:
        self.strikes: list[dict[str, Any]] = []
        self.reporter: dict[str, Any] | None = None
        self.area_status: str | None = "reported"
        self.area_reporters: list[dict[str, Any]] = []
        self.fail = False

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if self.fail:
            raise RuntimeError("no such table: report_strikes")
        if "from public.report_strikes" in query and "user_id = $1 or" in query:
            user_id, mac = args
            return [
                s for s in self.strikes
                if s["user_id"] == user_id or (mac is not None and s["phone_mac"] == mac)
            ]
        if "from public.area_reports ar" in query:
            return self.area_reporters
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "insert into public.report_strikes" in query:
            (user_id, mac, report_id, area_id, step, reason, serious, given_by, given_at,
             status, starts_at, expires_at) = args
            row = _row(
                user_id=user_id, phone_mac=mac, report_id=report_id, area_id=area_id,
                step=step, reason=reason, serious=serious, given_by=given_by,
                given_at=given_at, status=status, starts_at=starts_at, expires_at=expires_at,
            )
            self.strikes.append(row)
            return row
        if "from public.reports r" in query:
            return self.reporter
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self.fail:
            raise RuntimeError("no such table: report_strikes")
        if "select id from public.report_strikes where report_id" in query:
            return next((s["id"] for s in self.strikes if s["report_id"] == args[0]), None)
        if "select status from public.areas" in query:
            return self.area_status
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def _resident(**kw: Any) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=kw.pop("id", uuid4()), role="general_user", email="juan@example.com",
        phone=PHONE, phone_verified=True, **kw,
    )


@pytest.mark.asyncio
async def test_giving_strikes_climbs_the_ladder_and_waits_for_a_second_check() -> None:
    db = _Db()
    resident = uuid4()
    db.reporter = {
        "reporter_id": resident, "role": "general_user", "phone": PHONE,
        "phone_verified": True, "area_id": uuid4(),
    }
    coordinator = AuthenticatedUser(id=uuid4(), role="sub_admin", email="c@example.com")
    statuses = []
    for _ in range(3):
        strike = await rs.give(
            db, report_id=uuid4(), reason="No fire; a joke.", serious=False,
            giver=coordinator, now=NOW,
        )
        statuses.append((strike.step, strike.status))
    assert statuses == [(1, "active"), (2, "active"), (3, "awaiting_confirmation")]
    # A new account on the same number keeps them.
    standing = await rs.standing_of(db, _resident(), now=NOW)
    assert standing.step == 3 and not standing.can_report


@pytest.mark.asyncio
async def test_a_report_is_marked_once_and_only_a_residents() -> None:
    db = _Db()
    report = uuid4()
    db.reporter = {
        "reporter_id": uuid4(), "role": "general_user", "phone": None,
        "phone_verified": False, "area_id": None,
    }
    giver = AuthenticatedUser(id=uuid4(), role="admin", email="a@example.com")
    await rs.give(db, report_id=report, reason="A prank.", serious=False, giver=giver, now=NOW)
    with pytest.raises(ConflictError):
        await rs.give(db, report_id=report, reason="Again.", serious=False, giver=giver, now=NOW)
    db.reporter = {**db.reporter, "role": "response_team"}
    with pytest.raises(BadRequestError):
        await rs.give(db, report_id=uuid4(), reason="Staff.", serious=False, giver=giver, now=NOW)
    # Spaces are not a reason: the resident reads it.
    with pytest.raises(BadRequestError):
        await rs.give(db, report_id=uuid4(), reason="  a  ", serious=False, giver=giver, now=NOW)


@pytest.mark.asyncio
async def test_a_paused_resident_is_refused_and_a_broken_lookup_lets_them_report() -> None:
    db = _Db()
    me = _resident()
    db.strikes.append(_row(user_id=me.id, given_at=datetime.now(UTC)))
    with pytest.raises(ReportingPausedError) as refused:
        await rs.assert_may_report(db, me)
    assert refused.value.details is not None
    assert refused.value.details["step"] == 1 and refused.value.details["removed"] is False
    db.fail = True
    await rs.assert_may_report(db, me)  # no exception: a real fire must get through


@pytest.mark.asyncio
async def test_staff_are_never_paused() -> None:
    db = _Db()
    staff = AuthenticatedUser(id=uuid4(), role="sub_admin", email="s@example.com")
    db.strikes.append(_row(user_id=staff.id, given_at=datetime.now(UTC)))
    await rs.assert_may_report(db, staff)


@pytest.mark.asyncio
async def test_verify_first_holds_the_neighbour_alert_until_staff_verify() -> None:
    db = _Db()
    prankster = uuid4()
    db.strikes.append(_row(user_id=prankster, step=2, given_at=NOW - timedelta(days=10)))
    db.area_reporters = [
        {"reporter_id": prankster, "role": "general_user", "phone": None, "phone_verified": False}
    ]
    area = uuid4()
    assert await rs.held_for_verification(db, area, now=NOW)
    # Someone in good standing reports the same fire: the alert goes.
    db.area_reporters.append(
        {"reporter_id": uuid4(), "role": "general_user", "phone": None, "phone_verified": False}
    )
    assert not await rs.held_for_verification(db, area, now=NOW)
    # Staff verified it: the alert goes.
    db.area_reporters.pop()
    db.area_status = "verified"
    assert not await rs.held_for_verification(db, area, now=NOW)
    # A broken lookup never holds an alert.
    db.area_status = "reported"
    db.fail = True
    assert not await rs.held_for_verification(db, area, now=NOW)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@pytest.fixture
def db() -> _Db:
    return _Db()


@pytest.fixture
def client(db: _Db) -> Iterator[TestClient]:
    app.dependency_overrides[get_database] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(person: AuthenticatedUser) -> None:
    app.dependency_overrides[get_current_user] = lambda: person


def test_a_paused_resident_gets_reporting_paused_with_when(
    client: TestClient, db: _Db
) -> None:
    me = _resident()
    db.strikes.append(_row(user_id=me.id, step=2, given_at=datetime.now(UTC)))
    _as(me)
    response = client.post(
        "/reports/submit",
        data={"device_lat": "14.5378", "device_lng": "121.0014"},
        files={"photo": ("fire.jpg", b"not read", "image/jpeg")},
    )
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["error"] == "reporting_paused"
    assert "911" in body["message"]
    assert body["details"]["step"] == 2 and body["details"]["paused_until"]


def test_the_resident_sees_their_standing(client: TestClient, db: _Db) -> None:
    me = _resident()
    strike = _row(user_id=me.id, step=1, given_at=datetime.now(UTC))
    db.strikes.append(strike)
    _as(me)
    body = client.get("/report-strikes/me").json()
    assert body["can_report"] is False and body["step"] == 1
    assert body["lesson_due"] == str(strike["id"])
    (view,) = body["strikes"]
    assert view["can_appeal"] is True and view["appeal_state"] == "none"
    assert "given_by" not in view  # never who gave it


def test_only_the_central_hub_reviews_strikes(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="sub_admin", email="c@example.com"))
    assert client.get("/report-strikes").status_code == 403
    _as(AuthenticatedUser(id=uuid4(), role="admin", email="sys@example.com"))
    response = client.get("/report-strikes", params={"view": "appeals"})
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_an_honest_reject_still_needs_no_prank_flag() -> None:
    from app.schemas.incident import IncidentRejectRequest

    plain = IncidentRejectRequest(reason="Smoke from burning leaves.")
    assert plain.prank is False and plain.serious is False
