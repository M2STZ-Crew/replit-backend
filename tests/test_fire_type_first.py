"""The fire type before the alarm, said by the first team on scene (hermetic,
v1.12.52).

23 Nov 2026: "they can't raise an alarm level if someone isn't fill-up the
fire type first. and the first one who can fill-up the fire type is the one
who comes the incident first"; "before to proceed with positive fire alarm,
someone should fill the fire type first".
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api.routes import alarm_requests
from app.core.exceptions import ConflictError
from app.services.fire_type import FIRST_ON_SCENE_WAIT, assert_first_on_scene

FIRST, OTHER = uuid4(), uuid4()
NOW = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)
MIGRATION = pathlib.Path(__file__).parent.parent / (
    "supabase/migrations/20261123120000_positive_alarm_after_fire_type.sql"
)


def _answer(org: object, *, agency: str = "fire_volunteer", after: timedelta) -> None:
    assert_first_on_scene(
        org_id=org,  # type: ignore[arg-type]
        first_org=FIRST,
        first_org_name="Pasay Fire Volunteers",
        first_agency=agency,
        arrived_at=NOW - after,
        now=NOW,
    )


def test_the_team_that_arrived_first_says_what_is_burning() -> None:
    _answer(FIRST, after=timedelta(seconds=10))


def test_another_team_waits_for_them() -> None:
    with pytest.raises(ConflictError) as refused:
        _answer(OTHER, after=timedelta(minutes=1))
    assert refused.value.error_code == "first_on_scene_answers"
    assert "Pasay Fire Volunteers arrived first" in refused.value.message


def test_after_five_minutes_any_fire_team_on_scene_may() -> None:
    _answer(OTHER, after=FIRST_ON_SCENE_WAIT)


def test_when_the_first_on_scene_was_not_a_fire_team_any_may() -> None:
    _answer(OTHER, agency="medical", after=timedelta(seconds=10))


@pytest.mark.parametrize("fire_type", [None, "structural"])
def test_no_alarm_before_the_fire_type(fire_type: str | None) -> None:
    area = {"designation": "Area 3", "fire_type": fire_type}
    if fire_type is None:
        with pytest.raises(ConflictError) as refused:
            alarm_requests._assert_fire_type_known(area)
        assert refused.value.error_code == "fire_type_first"
    else:
        alarm_requests._assert_fire_type_known(area)


def test_every_way_to_set_a_level_checks_it() -> None:
    source = pathlib.Path(alarm_requests.__file__).read_text(encoding="utf-8")
    # Asking, raising directly, and approving a request.
    assert source.count("_assert_fire_type_known(area)") == 3
    assert source.count("designation, fire_type ") == 3


def test_the_migration_moves_positive_fire_alarm_to_the_fire_type() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "old.fire_type is null and new.fire_type is not null" in sql
    assert sql.count("new.alarm_level := 'positive_fire_alarm'") == 1
    assert "new.status = 'verified'" not in sql
    assert "an alarm level needs the fire type first" in sql
    # The authority rules after it are 20261109090000's.
    assert "Fire Volunteer sub-admins may set ONLY positive_fire_alarm." in sql
