"""v11 lifecycle: the collapsed Accept, the retired dispatch step, false alarms.

These cover what v11 changed rather than what it kept — the v10 suite still
guards the parts the new version left alone. Everything here is hermetic: the
state machine and the schemas are pure, and the migration is read off disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.exceptions import ForbiddenError
from app.schemas.auth import AuthenticatedUser
from app.schemas.post_incident_report import PostIncidentReportCreate
from app.services.incident import (
    ALLOWED_TRANSITIONS,
    OFF_FEED_STATUSES,
    TERMINAL_STATUSES,
    active_area_sql,
    assert_can_accept,
    assert_coordinator,
    assert_transition,
)

_MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"

V11_STATUSES = {
    "reported",
    "verified",
    "en_route",
    "arrived",
    "fire_out",
    "post_incident_report",
    "closed",
    "rejected",
    "merged",
}


def _user(role: str, agency: str | None) -> AuthenticatedUser:
    return AuthenticatedUser(
        id="00000000-0000-0000-0000-000000000001",
        email="someone@example.com",
        role=role,
        agency_type=agency,
    )


def _report(**overrides: object) -> dict[str, object]:
    """A complete, valid Post-Incident Report payload."""
    payload: dict[str, object] = {
        "truck_label": "Apollo",
        "truck_type": "Fire truck",
        "driver_name": "Juan Dela Cruz",
        "roster": [{"name": "Juan Dela Cruz", "role": "Driver"}],
        "equipment_taken": ["2.5in hose x3"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# The dispatch step is gone (Section 2.5)
# --------------------------------------------------------------------------- #
def test_dispatched_is_not_a_status_any_more() -> None:
    """v11 §4.3 lists nine statuses, and 'dispatched' is not one of them."""
    assert set(ALLOWED_TRANSITIONS) == V11_STATUSES
    assert "dispatched" not in ALLOWED_TRANSITIONS
    for targets in ALLOWED_TRANSITIONS.values():
        assert "dispatched" not in targets


def test_accept_reaches_en_route_without_passing_through_dispatched() -> None:
    """The collapsed Accept: reported -> verified -> en_route, both hops legal."""
    assert_transition("reported", "verified")
    assert_transition("verified", "en_route")


def test_the_old_v10_vocabulary_is_gone() -> None:
    """'pending' and 'resolved' were renamed, not kept as aliases."""
    assert "pending" not in ALLOWED_TRANSITIONS
    assert "resolved" not in ALLOWED_TRANSITIONS
    assert "fire_out" in OFF_FEED_STATUSES
    assert "resolved" not in OFF_FEED_STATUSES


def test_fire_out_stays_off_the_feed_without_being_terminal() -> None:
    """The distinction that stops a fire-out Area swallowing the next fire.

    If 'fire_out' re-entered the active feed, a new report near a fire that is
    out but not yet closed would cluster into the old Area instead of opening a
    new one.
    """
    assert "fire_out" in OFF_FEED_STATUSES
    assert "fire_out" not in TERMINAL_STATUSES
    assert "'fire_out'" in active_area_sql()


# --------------------------------------------------------------------------- #
# Accept is open to every staff tier (Section 2.5.1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "role,agency",
    [
        ("admin", None),
        ("sub_admin", "fire_volunteer"),
        ("sub_admin", "bfp"),
        ("sub_admin", "police"),
        ("sub_admin", "medical"),
        ("sub_admin", "barangay"),
    ],
)
def test_every_staff_tier_may_accept(role: str, agency: str | None) -> None:
    """First to Accept wins, whoever they are — the v11 change in one assertion."""
    assert_can_accept(_user(role, agency))


@pytest.mark.parametrize(
    "role,agency", [("response_team", "fire_volunteer"), ("general_user", None)]
)
def test_accept_still_needs_staff(role: str, agency: str | None) -> None:
    """Accept commits an agency. A responder or a citizen cannot make that call."""
    with pytest.raises(ForbiddenError):
        assert_can_accept(_user(role, agency))


@pytest.mark.parametrize("agency", ["police", "medical", "barangay"])
def test_reject_stays_coordinator_only(agency: str) -> None:
    """v11 widened Accept but deliberately left Reject alone (Section 2.5.2)."""
    with pytest.raises(ForbiddenError) as excinfo:
        assert_coordinator(_user("sub_admin", agency), "reject incidents")
    assert "situational awareness only" in str(excinfo.value)


def test_an_observer_accepting_is_not_an_observer_rejecting() -> None:
    """The same user may Accept and may not Reject. Both rules, one person."""
    observer = _user("sub_admin", "police")
    assert_can_accept(observer)
    with pytest.raises(ForbiddenError):
        assert_coordinator(observer, "reject incidents")


# --------------------------------------------------------------------------- #
# False alarm on the Post-Incident Report (Section 2.5.3)
# --------------------------------------------------------------------------- #
def test_a_report_defaults_to_not_a_false_alarm() -> None:
    report = PostIncidentReportCreate.model_validate(_report())
    assert report.false_alarm is False
    assert report.false_alarm_note is None


def test_a_false_alarm_needs_a_narrative() -> None:
    """"False alarm" with no account of what the team found is refused."""
    with pytest.raises(ValidationError):
        PostIncidentReportCreate.model_validate(_report(false_alarm=True))


def test_a_blank_narrative_does_not_count() -> None:
    with pytest.raises(ValidationError):
        PostIncidentReportCreate.model_validate(
            _report(false_alarm=True, false_alarm_note="   ")
        )


def test_a_false_alarm_with_its_narrative_validates() -> None:
    report = PostIncidentReportCreate.model_validate(
        _report(false_alarm=True, false_alarm_note="Rubbish fire, already out.")
    )
    assert report.false_alarm is True
    assert report.false_alarm_note == "Rubbish fire, already out."


# --------------------------------------------------------------------------- #
# The migration and the code agree
# --------------------------------------------------------------------------- #
def _v11_migration() -> str:
    path = _MIGRATIONS / "20260920120000_v11_lifecycle.sql"
    assert path.exists(), "the v11 lifecycle migration is missing"
    return path.read_text(encoding="utf-8")


def test_the_migration_defines_exactly_the_statuses_the_code_uses() -> None:
    """A status in one and not the other is the drift this test exists to catch."""
    sql = _v11_migration()
    created = re.search(r"create type public\.area_status as enum \((.*?)\);", sql, re.S)
    assert created, "the migration does not create area_status"
    declared = set(re.findall(r"'([a-z_]+)'", created.group(1)))
    assert declared == V11_STATUSES


def test_the_migration_renames_rather_than_leaving_v10_values_behind() -> None:
    sql = _v11_migration()
    created = re.search(r"create type public\.area_status as enum \((.*?)\);", sql, re.S)
    assert created
    declared = set(re.findall(r"'([a-z_]+)'", created.group(1)))
    for gone in ("pending", "resolved", "dispatched"):
        assert gone not in declared


def test_the_migration_adds_the_false_alarm_pair() -> None:
    sql = _v11_migration()
    assert "false_alarm" in sql
    assert "false_alarm_note" in sql
    assert "post_incident_reports_false_alarm_needs_note" in sql


def test_the_migration_creates_the_acceptance_ledger() -> None:
    """Section 4.1, plus the two guarantees Section 11.1 and 10.2 ask for."""
    sql = _v11_migration()
    assert "create table if not exists public.area_acceptances" in sql
    # Idempotent per actor, and exactly one verifying Accept per Area.
    assert "area_acceptances_unique unique (area_id, user_id)" in sql
    assert "area_acceptances_one_first_idx" in sql
