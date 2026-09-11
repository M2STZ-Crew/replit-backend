"""Master Context v10 (hermetic): the Post-Incident Report step, team-captain
authority, observer Accept, Admin routing, and evacuation sites beyond Pasay."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.exceptions import ConflictError, ForbiddenError
from app.main import app
from app.schemas.admin import RouteIncidentRequest
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import EvacuationSiteCreate, EvacuationSiteUpdate
from app.schemas.post_incident_report import PostIncidentReportCreate
from app.services.audit import match_audit_rule
from app.services.incident import (
    ALLOWED_TRANSITIONS,
    COORDINATING_AGENCIES,
    OBSERVER_AGENCIES,
    OFF_FEED_STATUSES,
    TERMINAL_STATUSES,
    assert_can_accept,
    assert_team_captain,
    assert_transition,
    routable_agencies,
)

_MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _user(role: str, agency: str | None = None) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency)


def _report(**overrides: object) -> dict[str, object]:
    """A complete, valid Post-Incident Report payload."""
    payload: dict[str, object] = {
        "truck_label": "Apollo",
        "truck_type": "Fire truck",
        "driver_name": "Juan Dela Cruz",
        "roster": [
            {"name": "Juan Dela Cruz", "role": "Driver"},
            {"name": "Maria Santos", "role": "Nozzle"},
        ],
        "equipment_taken": ["2.5in hose x3", "SCBA x2"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Lifecycle (Section 2.5)
# --------------------------------------------------------------------------- #
def test_the_full_v10_path_is_allowed() -> None:
    path = [
        "pending", "verified", "dispatched", "en_route", "arrived",
        "resolved", "post_incident_report", "closed",
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        ("arrived", "closed"),  # cannot skip fire out
        ("resolved", "closed"),  # cannot skip the report
        ("pending", "post_incident_report"),
        ("post_incident_report", "resolved"),  # no going back
        ("closed", "post_incident_report"),
        ("rejected", "closed"),
    ],
)
def test_the_report_step_cannot_be_skipped_or_reversed(current: str, target: str) -> None:
    with pytest.raises(ConflictError):
        assert_transition(current, target)


def test_closed_is_terminal_and_off_the_feed() -> None:
    assert "closed" in TERMINAL_STATUSES
    assert ALLOWED_TRANSITIONS["closed"] == set()
    assert {"resolved", "post_incident_report", "closed"} <= set(OFF_FEED_STATUSES)


def _enum_values(enum_name: str) -> set[str]:
    """Every value the migrations give a Postgres enum, created or added later."""
    values: set[str] = set()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        created = re.search(
            rf"create type public\.{enum_name} as enum \((.*?)\);", text, re.S
        )
        if created:
            values.update(re.findall(r"'([a-z_]+)'", created.group(1)))
        values.update(
            re.findall(rf"alter type public\.{enum_name} add value if not exists '([a-z_]+)'", text)
        )
    return values


def test_every_lifecycle_status_exists_in_the_database_enum() -> None:
    """A status the state machine knows but the enum lacks would 500 on write."""
    assert set(ALLOWED_TRANSITIONS) <= _enum_values("area_status")


def test_the_lifecycle_trigger_stamps_the_two_new_statuses() -> None:
    definitions = [
        text
        for path in sorted(_MIGRATIONS.glob("*.sql"))
        if "function public.stamp_area_lifecycle()" in (text := path.read_text(encoding="utf-8"))
    ]
    latest = definitions[-1]
    assert "post_incident_report_at" in latest
    assert "closed_at" in latest


def test_the_enum_migration_is_split_from_its_users() -> None:
    """Postgres cannot use an enum value in the transaction that adds it.

    So the file adding 'post_incident_report' and 'closed' must do nothing else;
    see the note in migration 0020.
    """
    adding = [
        path
        for path in sorted(_MIGRATIONS.glob("*.sql"))
        if "add value if not exists 'post_incident_report'" in path.read_text(encoding="utf-8")
    ]
    assert len(adding) == 1
    statements = [
        line
        for line in adding[0].read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    assert statements
    assert all(s.startswith("alter type public.area_status add value") for s in statements)


# --------------------------------------------------------------------------- #
# Who files the Post-Incident Report
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agency", COORDINATING_AGENCIES)
def test_a_fire_agency_captain_files(agency: str) -> None:
    assert_team_captain(_user("sub_admin", agency))


@pytest.mark.parametrize("agency", OBSERVER_AGENCIES)
def test_an_observer_captain_does_not_file(agency: str) -> None:
    with pytest.raises(ForbiddenError) as excinfo:
        assert_team_captain(_user("sub_admin", agency))
    assert "situational awareness" in excinfo.value.message
    assert excinfo.value.details == {"agency_type": agency, "access": "observer"}


@pytest.mark.parametrize(
    "role,agency",
    [("admin", None), ("response_team", "fire_volunteer"), ("general_user", None)],
)
def test_only_the_team_captain_files(role: str, agency: str | None) -> None:
    """Members do not file individually, and Admin routes rather than captains."""
    with pytest.raises(ForbiddenError) as excinfo:
        assert_team_captain(_user(role, agency))
    assert "team captain" in excinfo.value.message


# --------------------------------------------------------------------------- #
# Observer Accept (Section 2.6.1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agency", OBSERVER_AGENCIES)
def test_observers_may_accept(agency: str) -> None:
    assert_can_accept(_user("sub_admin", agency))


@pytest.mark.parametrize(
    "role,agency",
    [
        ("sub_admin", "fire_volunteer"),
        ("sub_admin", "bfp"),
        ("admin", None),
        ("response_team", "police"),
    ],
)
def test_only_observers_accept(role: str, agency: str | None) -> None:
    """Coordinators verify and dispatch; they are not shown an Accept control."""
    with pytest.raises(ForbiddenError):
        assert_can_accept(_user(role, agency))


# --------------------------------------------------------------------------- #
# The report form: single submit, fully filled
# --------------------------------------------------------------------------- #
def test_a_complete_report_validates() -> None:
    report = PostIncidentReportCreate.model_validate(_report(notes="  "))
    assert report.truck_label == "Apollo"
    assert len(report.roster) == 2
    assert report.notes is None  # blank notes are not a note


@pytest.mark.parametrize(
    "overrides",
    [
        {"truck_label": "   "},
        {"truck_type": ""},
        {"driver_name": " "},
        {"roster": []},
        {"roster": [{"name": "  "}]},
        {"equipment_taken": []},
        {"equipment_taken": ["", "  "]},
    ],
)
def test_an_incomplete_report_is_refused(overrides: dict[str, object]) -> None:
    """There is no draft state, so a report missing anything is not accepted."""
    with pytest.raises(ValidationError):
        PostIncidentReportCreate.model_validate(_report(**overrides))


def test_equipment_is_trimmed_and_deduplicated_in_order() -> None:
    report = PostIncidentReportCreate.model_validate(
        _report(equipment_taken=[" SCBA ", "Hose", "scba", "Axe"])
    )
    assert report.equipment_taken == ["SCBA", "Hose", "Axe"]


def test_a_blank_roster_role_becomes_none() -> None:
    report = PostIncidentReportCreate.model_validate(_report(roster=[{"name": "A", "role": " "}]))
    assert report.roster[0].role is None


# --------------------------------------------------------------------------- #
# Admin routing (Section 2.6.2)
# --------------------------------------------------------------------------- #
def test_routing_to_several_agencies_at_once() -> None:
    team = uuid4()
    request = RouteIncidentRequest.model_validate(
        {
            "routes": [
                {"agency": "fire_volunteer"},
                {"agency": "medical", "organization_ids": [str(team), str(team)]},
                {"agency": "police"},
            ]
        }
    )
    assert [r.agency for r in request.routes] == ["fire_volunteer", "medical", "police"]
    assert request.routes[1].organization_ids == [team]  # de-duplicated
    assert request.routes[0].organization_ids == []  # the agency as a whole


@pytest.mark.parametrize(
    "routes",
    [
        [],
        [{"agency": "police"}, {"agency": "police"}],
        [{"agency": "coast_guard"}],
    ],
)
def test_bad_route_requests_are_refused(routes: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        RouteIncidentRequest.model_validate({"routes": routes})


def test_routing_follows_what_the_reporter_asked_for() -> None:
    """An agency nobody requested stays unroutable, so visibility stays scoped."""
    assert routable_agencies(["medical"]) == {"medical"}
    assert "police" not in routable_agencies(["fire_volunteer", "medical"])
    assert routable_agencies([]) == set()


def test_the_fire_agencies_route_as_a_pair() -> None:
    """The SOS screen offers "fire"; BFP must be routable when Fire Volunteer is."""
    assert routable_agencies(["fire_volunteer"]) == {"fire_volunteer", "bfp"}
    assert routable_agencies(["bfp", "police"]) == {"fire_volunteer", "bfp", "police"}


# --------------------------------------------------------------------------- #
# Audit: the v10 actions write their own rows, so the middleware must not
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    [
        "/incidents/{id}/accept",
        "/incidents/{id}/post-incident-report",
        "/admin/incidents/{id}/route",
    ],
)
def test_v10_actions_are_not_double_audited(path: str) -> None:
    assert match_audit_rule("POST", path.format(id=uuid4())) is None


# --------------------------------------------------------------------------- #
# Evacuation sites beyond Pasay (Section 2.4)
# --------------------------------------------------------------------------- #
def test_a_new_site_defaults_to_pasay() -> None:
    site = EvacuationSiteCreate(name="Cuneta Astrodome", latitude=14.54, longitude=120.99)
    assert site.city == "Pasay City"


def test_a_site_may_be_outside_pasay() -> None:
    site = EvacuationSiteCreate(
        name="Parañaque shelter", latitude=14.48, longitude=121.01, city="Parañaque City"
    )
    assert site.city == "Parañaque City"


def test_city_can_be_changed_but_not_cleared() -> None:
    assert EvacuationSiteUpdate(city="Makati City").city == "Makati City"
    assert "city" not in EvacuationSiteUpdate(name="x").model_fields_set
    with pytest.raises(ValidationError):
        EvacuationSiteUpdate.model_validate({"city": None})


# --------------------------------------------------------------------------- #
# The new endpoints require a bearer token
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"/incidents/{uuid4()}/accept"),
        ("post", f"/incidents/{uuid4()}/post-incident-report"),
        ("get", f"/incidents/{uuid4()}/post-incident-report"),
        ("get", "/post-incident-reports"),
        ("post", f"/admin/incidents/{uuid4()}/route"),
    ],
)
def test_v10_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401
