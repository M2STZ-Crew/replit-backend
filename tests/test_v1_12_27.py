"""Backend v1.12.27 (12 Nov 2026): what this release pins.

- Adults only: a date of birth under 18 is refused (app/services/age.py),
  counted on the Philippine calendar.
- "50m actual incident, 100m corroboration": an Area gathers reports within
  50 m, overlaps are flagged within 100 m, and neighbours within 100 m are
  asked to corroborate.
- A Coordinator's or Responder's report counts as fully verified (PRD v14
  §4.1): V = 1.0 whatever their own profile shows.
- What is burning, set on scene (PRD v14 §4.5.3): six types, the subtypes of
  the three that have them, no Agricultural.
- The page an emailed link lands on can carry a button back to the app.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.routes import auth
from app.api.routes.reports import _reporter_verified_percent
from app.core.exceptions import BadRequestError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import FireTypeRequest, IncidentDetail, IncidentSummary
from app.services import clustering
from app.services.age import (
    MINIMUM_AGE,
    UnderageError,
    age_on,
    ensure_adult,
    today_in_manila,
)
from app.services.fire_type import FIRE_SUBTYPES, ON_SCENE_STATUSES, validate_fire_type
from app.services.link_page import link_page, open_app_href
from app.workers.neighborhood import NEIGHBORHOOD_RADIUS_M


# --------------------------------------------------------------------------- #
# 18 and over
# --------------------------------------------------------------------------- #
def test_the_minimum_age_is_eighteen() -> None:
    assert MINIMUM_AGE == 18


def test_a_birthday_not_reached_yet_this_year_does_not_count() -> None:
    assert age_on(date(2008, 11, 13), date(2026, 11, 12)) == 17
    assert age_on(date(2008, 11, 12), date(2026, 11, 12)) == 18
    assert age_on(date(2008, 2, 29), date(2026, 2, 28)) == 17
    assert age_on(date(2008, 2, 29), date(2026, 3, 1)) == 18


def test_seventeen_is_refused_and_says_why() -> None:
    with pytest.raises(UnderageError) as caught:
        ensure_adult(date(2008, 11, 13), today=date(2026, 11, 12))
    assert caught.value.error_code == "underage"
    assert caught.value.status_code == 400
    assert caught.value.details == {"field": "date_of_birth", "minimum_age": 18}
    assert "18 or older" in caught.value.message


def test_eighteen_today_and_no_date_at_all_pass() -> None:
    ensure_adult(date(2008, 11, 12), today=date(2026, 11, 12))
    ensure_adult(None)


def test_a_birth_date_in_the_future_is_refused() -> None:
    with pytest.raises(BadRequestError) as caught:
        ensure_adult(date(2027, 1, 1), today=date(2026, 11, 12))
    assert caught.value.error_code == "invalid_date_of_birth"


def test_today_is_the_philippine_date() -> None:
    # 20:00 UTC on 11 November is 04:00 on 12 November in Manila.
    assert today_in_manila(datetime(2026, 11, 11, 20, 0, tzinfo=UTC)) == date(2026, 11, 12)


def test_sign_up_and_the_profile_check_the_age() -> None:
    assert "ensure_adult(payload.date_of_birth)" in inspect.getsource(auth.signup)
    assert "ensure_adult(payload.date_of_birth)" in inspect.getsource(auth.update_my_profile)


# --------------------------------------------------------------------------- #
# 50 m incident, 100 m corroboration
# --------------------------------------------------------------------------- #
def test_an_area_gathers_reports_within_fifty_metres() -> None:
    assert clustering.CLUSTER_RADIUS_M == 50
    assert clustering._CLUSTER_RADIUS_M == 50


def test_two_areas_within_a_hundred_metres_may_be_one_fire() -> None:
    assert clustering._OVERLAP_RADIUS_M == 100


def test_neighbours_within_a_hundred_metres_are_asked_to_corroborate() -> None:
    assert NEIGHBORHOOD_RADIUS_M == 100


# --------------------------------------------------------------------------- #
# Staff reports count fully
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", ["sub_admin", "response_team", "admin"])
def test_a_staff_report_carries_full_verification(role: str) -> None:
    staff = AuthenticatedUser(id=uuid4(), role=role, verified_percent=0)
    assert _reporter_verified_percent(staff) == 100


def test_a_residents_report_carries_their_own() -> None:
    resident = AuthenticatedUser(id=uuid4(), role="general_user", verified_percent=50)
    assert _reporter_verified_percent(resident) == 50


# --------------------------------------------------------------------------- #
# What is burning
# --------------------------------------------------------------------------- #
def test_the_six_fire_types_and_no_agricultural() -> None:
    assert list(FIRE_SUBTYPES) == [
        "structural",
        "electrical",
        "vehicular",
        "rubbish",
        "grass",
        "chemical",
    ]
    assert FIRE_SUBTYPES["structural"] == ("residential", "commercial", "industrial")
    assert all("agricultural" not in subs for subs in FIRE_SUBTYPES.values())


def test_a_type_with_subtypes_needs_one_of_its_own() -> None:
    assert validate_fire_type("structural", "Residential") == "residential"
    assert validate_fire_type("vehicular", "e_bike") == "e_bike"
    with pytest.raises(BadRequestError) as missing:
        validate_fire_type("structural", None)
    assert missing.value.error_code == "invalid_fire_subtype"
    with pytest.raises(BadRequestError):
        validate_fire_type("structural", "agricultural")
    with pytest.raises(BadRequestError):
        validate_fire_type("electrical", "sedan")


def test_a_type_without_subtypes_takes_none() -> None:
    assert validate_fire_type("rubbish", None) is None
    assert validate_fire_type("grass", "  ") is None
    with pytest.raises(BadRequestError):
        validate_fire_type("chemical", "residential")


def test_it_is_set_on_scene_only() -> None:
    assert ON_SCENE_STATUSES == {"arrived", "fire_out", "post_incident_report"}


def test_the_request_and_the_incident_carry_it() -> None:
    body = FireTypeRequest(fire_type="structural", fire_subtype="residential")
    assert body.fire_type == "structural"
    with pytest.raises(ValidationError):
        FireTypeRequest(fire_type="agricultural")  # type: ignore[arg-type]
    assert {"fire_type", "fire_subtype", "fire_type_set_at"} <= set(IncidentSummary.model_fields)
    assert "fire_type_set_by_name" in IncidentDetail.model_fields


def test_the_route_is_there() -> None:
    paths = {
        (getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", ()) or ()))) for r in app.routes
    }
    assert ("/incidents/{incident_id}/fire-type", ("POST",)) in paths


# --------------------------------------------------------------------------- #
# Back to the app
# --------------------------------------------------------------------------- #
def test_the_way_back_to_the_app_suits_the_phone() -> None:
    assert open_app_href("Mozilla/5.0 (Linux; Android 14)") == (
        "intent://email-confirmed#Intent;scheme=reportwhatslit;end"
    )
    assert open_app_href("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1)") == (
        "reportwhatslit://email-confirmed"
    )
    assert open_app_href(None) == "reportwhatslit://email-confirmed"


def test_a_page_without_an_action_has_no_button() -> None:
    page = link_page("t", "Heading", "Message")
    assert 'class="action"' not in bytes(page.body).decode()
    page = link_page("t", "Heading", "Message", action=("Open RepLiT", "x://y?a=1&b=2"))
    assert '<a class="action" href="x://y?a=1&amp;b=2">Open RepLiT</a>' in bytes(page.body).decode()
