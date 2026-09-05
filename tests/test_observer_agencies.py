"""Observer sub-admins (police, medical, barangay) are read-only on incidents.

Section 1.3 problem 9 wants cross-agency situational awareness, but only the fire
agencies coordinate the response. A police sub-admin must be able to see an
incident that requested police and do nothing else to it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenError
from app.schemas.auth import AuthenticatedUser
from app.services.incident import (
    COORDINATING_AGENCIES,
    OBSERVER_AGENCIES,
    assert_coordinator,
    is_coordinator,
    is_observer,
    visible_agencies,
)


def _user(role: str, agency: str | None) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        email="x@example.com",
        role=role,
        agency_type=agency,
        verified_percent=0,
        badge="yellow",
    )


# --------------------------------------------------------------------------- #
# Who coordinates
# --------------------------------------------------------------------------- #
def test_the_two_fire_agencies_coordinate() -> None:
    for agency in COORDINATING_AGENCIES:
        assert is_coordinator(_user("sub_admin", agency)) is True, agency


def test_observer_agencies_do_not_coordinate() -> None:
    for agency in OBSERVER_AGENCIES:
        user = _user("sub_admin", agency)
        assert is_coordinator(user) is False, agency
        assert is_observer(user) is True, agency


def test_the_two_sets_do_not_overlap() -> None:
    assert set(COORDINATING_AGENCIES).isdisjoint(OBSERVER_AGENCIES)


def test_every_agency_type_is_classified() -> None:
    """A new agency_type must be placed deliberately, not default to coordinator."""
    all_agencies = {"fire_volunteer", "bfp", "police", "medical", "barangay"}
    assert set(COORDINATING_AGENCIES) | set(OBSERVER_AGENCIES) == all_agencies


def test_admin_keeps_full_authority() -> None:
    assert is_coordinator(_user("admin", None)) is True


def test_a_response_team_member_is_not_a_coordinator() -> None:
    # They advance their own dispatch, but never reject or resolve.
    assert is_coordinator(_user("response_team", "fire_volunteer")) is False


def test_a_citizen_is_not_a_coordinator() -> None:
    assert is_coordinator(_user("general_user", None)) is False


# --------------------------------------------------------------------------- #
# The guard
# --------------------------------------------------------------------------- #
def test_assert_coordinator_admits_fire_agencies() -> None:
    assert_coordinator(_user("sub_admin", "fire_volunteer"), "reject incidents")
    assert_coordinator(_user("sub_admin", "bfp"), "reject incidents")
    assert_coordinator(_user("admin", None), "reject incidents")


@pytest.mark.parametrize("agency", OBSERVER_AGENCIES)
def test_assert_coordinator_refuses_observers(agency: str) -> None:
    with pytest.raises(ForbiddenError) as excinfo:
        assert_coordinator(_user("sub_admin", agency), "resolve incidents")
    error = excinfo.value
    # The message must explain the standing, not just deny: a Barangay sub-admin
    # should understand they observe rather than assume the system is broken.
    assert "situational awareness" in error.message
    assert "resolve incidents" in error.message
    assert error.details == {"agency_type": agency, "access": "observer"}


def test_a_responder_refusal_does_not_claim_observer_status() -> None:
    with pytest.raises(ForbiddenError) as excinfo:
        assert_coordinator(_user("response_team", "fire_volunteer"), "dispatch responders")
    assert "situational awareness" not in excinfo.value.message


# --------------------------------------------------------------------------- #
# Observers still SEE their incidents — that is the whole point
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agency", OBSERVER_AGENCIES)
def test_an_observer_sees_incidents_that_requested_their_agency(agency: str) -> None:
    assert visible_agencies(_user("sub_admin", agency)) == [agency]


def test_fire_agencies_keep_two_way_visibility() -> None:
    for agency in COORDINATING_AGENCIES:
        assert set(visible_agencies(_user("sub_admin", agency))) == set(COORDINATING_AGENCIES)


def test_an_observer_cannot_see_a_fire_only_incident() -> None:
    """Visibility is scoped to their own agency, so a fire-only report stays hidden."""
    police = visible_agencies(_user("sub_admin", "police"))
    assert "fire_volunteer" not in police
    assert "bfp" not in police


def test_admin_sees_everything() -> None:
    assert visible_agencies(_user("admin", None)) is None
