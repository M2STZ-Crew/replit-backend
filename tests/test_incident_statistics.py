"""The Admin Dashboard's statistics (hermetic, v1.12.50).

22 Nov 2026, answered "Statistics dashboard": what these pin:
- days are Manila's, and the period before is the same length of time;
- no change is made up for a time before the records (reset 13 Nov 2026);
- a false alarm is counted as one, and is no fire;
- an organization's Admin reads its own by default and may read all, the
  central hub and the system Admin always all, and nobody but Admins any.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import incident_statistics as stats

NOW = datetime(2026, 11, 22, 15, 0, tzinfo=stats.MANILA)
ORG = uuid4()


def _at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=stats.MANILA)


def _fire(reported: datetime, **cols: Any) -> dict[str, Any]:
    return {
        "reported_at": reported,
        "verified_at": None,
        "acknowledged_at": None,
        "arrived_at": None,
        "alarm_level": None,
        "fire_type": None,
        "barangay_pcode": None,
        "barangay_name": None,
        "barangay_city": None,
        "false_alarm": False,
        **cols,
    }


def _summary(rows: list[dict[str, Any]], since: datetime | None = None) -> Any:
    return stats.summarise(rows, days=7, scope="all", now=NOW, since=since or _at(1))


# --------------------------------------------------------------------------- #
# Periods
# --------------------------------------------------------------------------- #
def test_seven_days_is_today_and_the_six_before() -> None:
    start, before, before_end = stats.windows(7, NOW)
    assert start == _at(16, 0)
    assert before == _at(9, 0)
    # As far into its last day as now is into today.
    assert before_end == _at(15, 15)


def test_the_day_is_manila_s_whatever_the_clock_is_set_to() -> None:
    utc = datetime.fromisoformat("2026-11-21T17:00:00+00:00")  # 1 AM on the 22nd in Manila
    assert stats.windows(7, utc)[0] == _at(16, 0)


@pytest.mark.parametrize(("days", "length"), [(7, 7), (30, 30), (90, 90)])
def test_both_periods_are_as_long(days: int, length: int) -> None:
    start, before, before_end = stats.windows(days, NOW)
    assert start - before == timedelta(days=length)
    assert before_end - before == NOW - start
    assert before_end <= start


def test_no_change_for_a_time_before_the_records() -> None:
    rows = [_fire(_at(14)), _fire(_at(20))]
    after_the_reset = _summary(rows, since=_at(13, 10))
    assert not after_the_reset.comparable
    assert after_the_reset.fires.value == 1 and after_the_reset.fires.previous is None
    # Records from the period's first day, at whatever hour, cover it.
    assert _summary(rows, since=_at(9, 22)).comparable


def test_nothing_on_record_compares_nothing() -> None:
    out = stats.summarise([], days=7, scope="all", now=NOW, since=None)
    assert not out.comparable
    assert out.fires.value == 0 and out.fires.previous is None
    assert out.minutes_to_acknowledge.value is None and out.false_alarms.value is None
    assert [d.count for d in out.per_day] == [0] * 7


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #
def test_the_four_measures_against_the_period_before() -> None:
    def answered(day: int, ack: int, scene: int) -> dict[str, Any]:
        reported = _at(day)
        acked = reported + timedelta(minutes=ack)
        return _fire(
            reported,
            verified_at=acked,
            acknowledged_at=acked,
            arrived_at=acked + timedelta(minutes=scene),
        )

    out = _summary(
        [
            answered(20, 1, 6),
            answered(21, 2, 8),
            answered(22, 6, 30),  # the median is not moved by one slow night
            _fire(_at(18), false_alarm=True),
            answered(12, 4, 5),
        ]
    )
    ack, scene = out.minutes_to_acknowledge, out.minutes_to_scene
    assert (ack.value, ack.n, ack.previous) == (2.0, 3, 4.0)
    assert (scene.value, scene.n, scene.previous) == (8.0, 3, 5.0)
    assert (out.fires.value, out.fires.previous) == (3, 1)
    assert (out.false_alarms.value, out.false_alarms.n, out.false_alarms.previous) == (0.25, 4, 0.0)


def test_on_scene_is_from_the_first_acknowledgement() -> None:
    row = _fire(
        _at(20, 9),
        verified_at=_at(20, 9, 2),
        acknowledged_at=_at(20, 9, 20),  # our organization came later
        arrived_at=_at(20, 9, 12),
    )
    assert _summary([row]).minutes_to_scene.value == 10.0


def test_the_later_part_of_the_last_day_before_is_not_compared() -> None:
    out = _summary([_fire(_at(15, 14)), _fire(_at(15, 18))])
    assert out.fires.value == 0 and out.fires.previous == 1


def test_per_day_is_every_manila_day_in_order() -> None:
    utc = datetime.fromisoformat("2026-11-16T17:30:00+00:00")  # 1:30 AM on the 17th
    out = _summary([_fire(utc), _fire(_at(22, 1)), _fire(_at(22, 2))])
    assert [d.day for d in out.per_day] == [date(2026, 11, n) for n in range(16, 23)]
    assert [d.count for d in out.per_day] == [0, 1, 0, 0, 0, 0, 2]


def test_the_charts_count_fires_not_false_alarms() -> None:
    here = {"barangay_pcode": "PH76", "barangay_name": "Barangay 76", "barangay_city": "Pasay"}
    out = _summary(
        [
            _fire(_at(20), alarm_level="third_alarm", fire_type="structural", **here),
            _fire(_at(20), alarm_level="positive_fire_alarm", fire_type="structural", **here),
            _fire(_at(21)),
            _fire(_at(21), false_alarm=True, fire_type="grass", **here),
        ]
    )
    assert [(b.name, b.city, b.count) for b in out.barangays] == [("Barangay 76", "Pasay", 2)]
    assert out.without_barangay == 1
    assert [(t.key, t.count) for t in out.fire_types] == [("structural", 2), (None, 1)]
    levels = [(level.key, level.count) for level in out.alarm_levels]
    assert levels[0] == ("positive_fire_alarm", 1) and ("third_alarm", 1) in levels
    assert levels[-1] == (None, 1)
    assert sum(count for _, count in levels) == out.fires.value


def test_the_five_barangays_with_the_most_ties_by_name() -> None:
    rows = [
        _fire(
            _at(20),
            barangay_pcode=f"PH{n}",
            barangay_name=f"Barangay {n}",
            barangay_city="Pasay",
        )
        for n in (7, 6, 5, 4, 3, 2, 2)
    ]
    names = [b.name for b in _summary(rows).barangays]
    assert names == [f"Barangay {n}" for n in (2, 3, 4, 5, 6)]


# --------------------------------------------------------------------------- #
# Who reads what
# --------------------------------------------------------------------------- #
class _Db:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[Any, ...] = ()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.sql, self.args = " ".join(query.split()), args
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert "min(reported_at)" in query
        return None


@pytest.fixture
def get() -> Iterator[Any]:
    with TestClient(app) as client:

        def call(user: AuthenticatedUser, query: str = "") -> tuple[Any, _Db]:
            db = _Db()
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_database] = lambda: db
            return client.get(f"/incidents/statistics{query}"), db

        yield call
    app.dependency_overrides.clear()


def _admin(agency: str | None = "police", *, hub: bool = False) -> AuthenticatedUser:
    if agency is None:
        return AuthenticatedUser(id=uuid4(), role="admin", phone_verified=True)
    return AuthenticatedUser(
        id=uuid4(),
        role="admin",
        phone_verified=True,
        primary_org_id=ORG,
        org_name="An organization",
        org_agency_type=agency,
        org_is_active=True,
        org_is_central_hub=hub,
    )


@pytest.mark.parametrize(
    ("agency", "acts_on"),
    [("police", ["police"]), ("bfp", ["fire_volunteer", "bfp"])],
)
def test_an_organization_s_admin_reads_its_own_by_default(
    get: Any, agency: str, acts_on: list[str]
) -> None:
    res, db = get(_admin(agency))
    assert res.status_code == 200
    assert (res.json()["scope"], res.json()["days"]) == ("org", 30)
    assert db.args[2:] == (acts_on, ORG)
    assert "r.selected_agencies && $3::public.agency_type[]" in db.sql
    assert "x.organization_id = $4" in db.sql


def test_it_may_switch_to_all_incidents(get: Any) -> None:
    res, db = get(_admin(), "?scope=all&days=90")
    assert (res.json()["scope"], res.json()["days"]) == ("all", 90)
    assert len(res.json()["per_day"]) == 90
    assert len(db.args) == 2 and "$3" not in db.sql


@pytest.mark.parametrize(("agency", "hub"), [("barangay", True), (None, False)])
def test_the_hub_and_the_system_admin_always_read_all(
    get: Any, agency: str | None, hub: bool
) -> None:
    res, db = get(_admin(agency, hub=hub), "?scope=org")
    assert res.json()["scope"] == "all"
    assert len(db.args) == 2


def test_merged_fires_are_left_out(get: Any) -> None:
    _, db = get(_admin(None))
    assert "a.status::text <> 'merged'" in db.sql


@pytest.mark.parametrize(
    ("query", "status"), [("?days=8", 400), ("?days=x", 422), ("?scope=mine", 422)]
)
def test_only_the_three_periods_and_two_scopes(get: Any, query: str, status: int) -> None:
    assert get(_admin(), query)[0].status_code == status


@pytest.mark.parametrize("role", ["general_user", "response_team", "sub_admin"])
def test_only_admins(get: Any, role: str) -> None:
    user = AuthenticatedUser(
        id=uuid4(),
        role=role,
        agency_type=None if role == "general_user" else "fire_volunteer",
        primary_org_id=ORG,
        phone_verified=True,
        email_verified=True,
    )
    res, db = get(user)
    assert res.status_code == 403
    assert not db.sql
