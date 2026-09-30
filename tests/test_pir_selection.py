"""The Post-Incident Report, filled by selection (hermetic).

The captain no longer types anything: the report records the time of the
incident and the time the fire was out, every unit that went, the driver and
the roster picked from the organisation's members, and the equipment taken.
These pin the new shape, that an app build from before the change can still
file, and the members list the pickers are filled from.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user, get_database
from app.api.routes import post_incident_reports
from app.api.routes.post_incident_reports import _to_response
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.post_incident_report import PostIncidentReportCreate

_APOLLO, _HERMES = uuid4(), uuid4()
_STARTED = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
_OUT = datetime(2026, 9, 30, 8, 40, tzinfo=UTC)


def _report(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "incident_at": _STARTED.isoformat(),
        "fire_out_at": _OUT.isoformat(),
        "units": [
            {"name": "Apollo", "type": "Fire Truck", "equipment_id": str(_APOLLO)},
            {"name": "Hermes", "type": "Fire Truck", "equipment_id": str(_HERMES)},
        ],
        "driver_name": "Paolo Villareal",
        "driver_user_id": str(uuid4()),
        "roster": [
            {"name": "Paolo Villareal", "user_id": str(uuid4())},
            {"name": "Jericho Manalo", "user_id": str(uuid4())},
        ],
        "equipment_taken": ["Hose line", "SCBA"],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ the report ---
def test_a_report_made_of_selections_validates() -> None:
    report = PostIncidentReportCreate.model_validate(_report())
    assert report.incident_at == _STARTED
    assert report.fire_out_at == _OUT
    assert [u.name for u in report.units] == ["Apollo", "Hermes"]
    # What the single-truck columns hold, for anything still reading them.
    assert report.unit_names == "Apollo, Hermes"
    assert report.unit_types == "Fire Truck"
    assert [m.role for m in report.roster] == [None, None]
    assert report.notes is None


def test_the_times_may_be_left_to_the_system() -> None:
    """They default to what was recorded; the captain only corrects them."""
    report = PostIncidentReportCreate.model_validate(
        _report(incident_at=None, fire_out_at=None)
    )
    assert report.incident_at is None and report.fire_out_at is None
    source = " ".join(
        inspect.getsource(post_incident_reports.file_post_incident_report).split()
    )
    assert 'payload.incident_at or times["reported_at"]' in source
    assert 'payload.fire_out_at or times["resolved_at"]' in source


def test_the_fire_cannot_be_out_before_it_started() -> None:
    with pytest.raises(ValidationError, match="before the incident"):
        PostIncidentReportCreate.model_validate(
            _report(fire_out_at=(_STARTED - timedelta(minutes=1)).isoformat())
        )


def test_a_time_that_has_not_happened_is_refused() -> None:
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    with pytest.raises(ValidationError, match="not happened yet"):
        PostIncidentReportCreate.model_validate(_report(fire_out_at=later))


def test_a_time_with_no_zone_is_read_as_utc() -> None:
    report = PostIncidentReportCreate.model_validate(
        _report(incident_at="2026-09-30T08:00:00", fire_out_at="2026-09-30T08:40:00")
    )
    assert report.incident_at == _STARTED


def test_the_same_unit_picked_twice_counts_once() -> None:
    twice = _report()["units"] + [{"name": "Apollo", "equipment_id": str(_APOLLO)}]
    report = PostIncidentReportCreate.model_validate(_report(units=twice))
    assert report.unit_names == "Apollo, Hermes"


@pytest.mark.parametrize("missing", ["units", "driver_name", "roster", "equipment_taken"])
def test_nothing_may_be_left_unselected(missing: str) -> None:
    payload = _report()
    del payload[missing]
    with pytest.raises(ValidationError):
        PostIncidentReportCreate.model_validate(payload)


def test_a_false_alarm_carries_the_reason_that_was_picked() -> None:
    with pytest.raises(ValidationError, match="false alarm"):
        PostIncidentReportCreate.model_validate(_report(false_alarm=True))
    report = PostIncidentReportCreate.model_validate(
        _report(false_alarm=True, false_alarm_note="Fire already out")
    )
    assert report.false_alarm_note == "Fire already out"


def test_an_app_from_before_the_change_can_still_file() -> None:
    """It posts one typed truck and no units; refusing it would stop every
    captain who has not updated from closing an incident."""
    report = PostIncidentReportCreate.model_validate(
        {
            "truck_label": "Apollo",
            "truck_type": "Fire truck",
            "truck_equipment_id": str(_APOLLO),
            "driver_name": "Juan Dela Cruz",
            "roster": [{"name": "Juan Dela Cruz", "role": "Driver"}],
            "equipment_taken": ["Hose"],
            "notes": "Hydrant was dry.",
        }
    )
    assert [(u.name, u.type, u.equipment_id) for u in report.units] == [
        ("Apollo", "Fire truck", _APOLLO)
    ]
    assert report.notes == "Hydrant was dry."


# ------------------------------------------------------- reading it back ---
def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(), "area_id": uuid4(), "area_designation": "Area 7",
        "resolved_at": _OUT, "incident_at": _STARTED, "fire_out_at": _OUT,
        "filed_by": uuid4(), "filed_by_name": "Ramon Dizon", "filed_by_role": "sub_admin",
        "filed_by_agency": "fire_volunteer", "organization_id": None,
        "organization_name": "Hercules Fire Brigade",
        "units": '[{"name": "Apollo", "type": "Fire Truck", "equipment_id": null}]',
        "truck_equipment_id": None, "truck_label": "Apollo", "truck_type": "Fire Truck",
        "driver_name": "Paolo Villareal", "driver_user_id": None,
        "roster": '[{"name": "Paolo Villareal"}]', "equipment_taken": ["Hose line"],
        "notes": None, "false_alarm": False, "false_alarm_note": None,
        "submitted_at": _OUT,
    }
    row.update(overrides)
    return row


def test_a_filed_report_reads_back_with_its_times_and_units() -> None:
    report = _to_response(_row())
    assert report.incident_at == _STARTED and report.fire_out_at == _OUT
    assert [u.name for u in report.units] == ["Apollo"]
    assert report.truck_label == "Apollo"


def test_a_report_from_before_units_were_recorded_reads_back_as_one() -> None:
    report = _to_response(_row(units=None, truck_label="Hermes", truck_type="Tanker"))
    assert [(u.name, u.type) for u in report.units] == [("Hermes", "Tanker")]


def test_the_query_falls_back_to_the_incidents_own_times() -> None:
    select = post_incident_reports._REPORT_SELECT
    assert "coalesce(p.incident_at, a.reported_at) as incident_at" in select
    assert "coalesce(p.fire_out_at, a.resolved_at) as fire_out_at" in select


# ---------------------------------------------------- who there is to pick ---
class _Db:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((" ".join(query.split()), args))
        return [
            {"id": uuid4(), "full_name": "Ramon Dizon", "role": "sub_admin",
             "agency_type": "fire_volunteer", "verified_percent": 0, "badge": "yellow"},
            {"id": uuid4(), "full_name": "Jericho Manalo", "role": "response_team",
             "agency_type": "fire_volunteer", "verified_percent": 0, "badge": "yellow"},
        ]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(user: AuthenticatedUser, db: _Db) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db


def test_a_captain_is_offered_their_own_organisations_members(client: TestClient) -> None:
    org, db = uuid4(), _Db()
    _as(AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="fire_volunteer",
                          primary_org_id=org), db)

    r = client.get("/organizations/mine/members")

    assert r.status_code == 200, r.text
    assert [m["full_name"] for m in r.json()] == ["Ramon Dizon", "Jericho Manalo"]
    query, args = db.calls[0]
    assert "where primary_org_id = $1" in query and args == (org,)
    # A member with no name on file is still listed under something pickable.
    assert "split_part(email, '@', 1)" in query


def test_a_responder_may_read_it_too(client: TestClient) -> None:
    db = _Db()
    _as(AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp",
                          primary_org_id=uuid4()), db)
    assert client.get("/organizations/mine/members").status_code == 200


def test_a_captain_with_no_organisation_is_offered_nobody(client: TestClient) -> None:
    """Strictly the coordinator's own organization: it used to fall back to every
    unattached staff account in the agency, which offered other teams' people."""
    db = _Db()
    _as(AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="bfp"), db)
    r = client.get("/organizations/mine/members")
    assert r.status_code == 200 and r.json() == []
    assert db.calls == []


def test_a_citizen_is_refused(client: TestClient) -> None:
    _as(AuthenticatedUser(id=uuid4(), role="general_user"), _Db())
    assert client.get("/organizations/mine/members").status_code == 403


def test_the_members_route_is_not_swallowed_by_the_org_id_route(client: TestClient) -> None:
    """"/mine/members" must not be read as an organisation id of "mine"."""
    db = _Db()
    _as(AuthenticatedUser(id=uuid4(), role="admin"), db)
    r = client.get("/organizations/mine/members")
    assert r.status_code == 200 and r.json() == []
    assert db.calls == []
