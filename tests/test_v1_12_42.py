"""v1.12.42: fires named after their streets, and the far-fire voice.

18 Nov 2026: "instead of area, it will be called 'Near [street]' or the street
itself ... '[street] corner [street]' or 'near [street]'" (answered "Corner,
else Near"; the Area number "Nowhere on screen"), and "create a placeholder
for voice for far incidents (outside 100m). and remain the sound of near
incident".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.integrations.fcm import (
    FAR_VOICE_SINCE,
    SOUND_CHANNELS_V2,
    android_config,
    far_voice,
    has_far_voice,
)
from app.services import clustering, place_names
from app.services.citizen_copy import fire_verified
from app.services.pdf_report import build_fire_out_pdf
from app.services.place_names import Place, degrees, find_place, in_language, place_name, where
from tests.test_phase14 import _facts

NEAR = "Near F. Victor Street"
CORNER = "Taft Avenue corner Gil Puyat Avenue"


# --------------------------------------------------------------------------- #
# The name
# --------------------------------------------------------------------------- #
def test_a_corner_names_both_streets_the_nearer_first() -> None:
    assert place_name(Place("Taft Avenue", "Gil Puyat Avenue"), 14.55, 120.99) == CORNER


def test_off_a_corner_the_fire_is_near_its_street() -> None:
    assert place_name(Place("F. Victor Street"), 14.53, 121.0) == NEAR


def test_a_second_live_fire_of_the_same_name_is_numbered() -> None:
    assert place_name(Place("F. Victor Street", None, 2), 14.53, 121.0) == f"{NEAR} (2)"
    assert place_name(Place("Taft Avenue", "Gil Puyat Avenue", 3), 14.55, 120.99) == (
        f"{CORNER} (3)"
    )


def test_with_no_street_near_the_fire_is_called_by_its_coordinates() -> None:
    assert place_name(Place(), 14.5378, 121.0014) == "14.5378° N, 121.0014° E"
    assert degrees(-1.5, -2.25) == "1.5000° S, 2.2500° W"


def test_tagalog_says_malapit_sa_and_keeps_a_corner_as_it_is() -> None:
    assert in_language(NEAR, "tl") == "Malapit sa F. Victor Street"
    assert in_language(f"{NEAR} (2)", "tl") == "Malapit sa F. Victor Street (2)"
    assert in_language(CORNER, "tl") == CORNER
    assert in_language(NEAR, "en") == NEAR
    assert in_language(None, "tl") == ""


def test_the_name_inside_a_sentence() -> None:
    assert where(NEAR, "en") == "near F. Victor Street"
    assert where(CORNER, "en") == f"at {CORNER}"
    assert where(NEAR, "tl") == "malapit sa F. Victor Street"
    assert where(CORNER, "tl") == f"sa {CORNER}"
    assert where("  ", "en") == ""


def test_the_verified_fire_alert_says_the_street_never_the_number() -> None:
    title, body = fire_verified("en", NEAR)
    assert title == "Fire verified"
    assert body.startswith("Responders verified a fire near F. Victor Street. Stay away")
    title, body = fire_verified("tl", CORNER)
    assert title == "Kumpirmadong sunog"
    assert body.startswith(f"Kinumpirma ng mga responder ang sunog sa {CORNER}. Lumayo")
    # No name at all still reads as a sentence.
    assert fire_verified("en", None)[1].startswith("Responders verified a fire. Stay away")


# --------------------------------------------------------------------------- #
# Finding the streets
# --------------------------------------------------------------------------- #
class _StreetsDb:
    """Answers find_place's lookups: the corner, the nearest street (within
    300 m, then 1.5 km), and the live fires already called the same."""

    def __init__(
        self,
        *,
        corner: dict[str, str] | None = None,
        near: dict[str, str] | None = None,
        far: dict[str, str] | None = None,
        taken: int | None = None,
        fail: bool = False,
    ) -> None:
        self.corner, self.near, self.far, self.taken, self.fail = corner, near, far, taken, fail
        self.rows: list[tuple[str, tuple[Any, ...]]] = []
        self.counted: tuple[Any, ...] | None = None

    async def fetchrow(self, query: str, *args: Any) -> dict[str, str] | None:
        self.rows.append((query, args))
        if self.fail:
            raise RuntimeError('relation "public.streets" does not exist')
        if "join near b" in query:
            return self.corner
        return self.near if args[2] == place_names.NEAR_RADIUS_M else self.far

    async def fetchval(self, query: str, *args: Any) -> int | None:
        self.counted = args
        assert "place_street = $1" in query and "is not distinct from $2" in query
        return self.taken


async def test_two_streets_meeting_within_30_m_make_a_corner() -> None:
    db = _StreetsDb(corner={"street": "Taft Avenue", "cross_street": "Gil Puyat Avenue"})
    place = await find_place(db, 14.5547, 120.9975)  # type: ignore[arg-type]
    assert place == Place("Taft Avenue", "Gil Puyat Avenue")
    query, args = db.rows[0]
    assert args == (14.5547, 120.9975, 30.0, 3.0)
    # Distances in metres: the point goes into the streets' UTM projection.
    assert "ST_Transform" in query and "32651" in query
    assert db.counted == ("Taft Avenue", "Gil Puyat Avenue", None)


async def test_without_a_corner_the_nearest_street_within_300_m() -> None:
    db = _StreetsDb(near={"name": "F. Victor Street"})
    assert await find_place(db, 14.5378, 121.0014) == Place("F. Victor Street")  # type: ignore[arg-type]
    assert [args[2] for _, args in db.rows[1:]] == [300.0]


async def test_farther_out_when_nothing_is_within_300_m() -> None:
    db = _StreetsDb(far={"name": "Roxas Boulevard"})
    assert await find_place(db, 14.53, 120.98) == Place("Roxas Boulevard")  # type: ignore[arg-type]
    assert [args[2] for _, args in db.rows[1:]] == [300.0, 1500.0]


async def test_no_street_within_1_5_km_leaves_the_fire_unnamed() -> None:
    assert await find_place(_StreetsDb(), 14.5, 121.0) == Place()  # type: ignore[arg-type]


async def test_a_live_fire_already_called_this_makes_it_the_second() -> None:
    db = _StreetsDb(near={"name": "F. Victor Street"}, taken=1)
    assert await find_place(db, 14.5, 121.0) == Place("F. Victor Street", None, 2)  # type: ignore[arg-type]
    db = _StreetsDb(near={"name": "F. Victor Street"}, taken=2)
    assert (await find_place(db, 14.5, 121.0)).number == 3  # type: ignore[arg-type]


async def test_an_area_named_again_does_not_count_itself() -> None:
    me = uuid4()
    db = _StreetsDb(near={"name": "F. Victor Street"})
    await find_place(db, 14.5, 121.0, leave_out=me)  # type: ignore[arg-type]
    assert db.counted == ("F. Victor Street", None, me)


async def test_a_failed_lookup_never_stops_a_report() -> None:
    assert await find_place(_StreetsDb(fail=True), 14.5, 121.0) == Place()  # type: ignore[arg-type]


async def test_a_new_area_is_named_and_keeps_its_number_as_its_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def named(db: Any, lat: float, lng: float, *, leave_out: UUID | None = None) -> Place:
        return Place("Taft Avenue", "Gil Puyat Avenue")

    monkeypatch.setattr(clustering, "find_place", named)
    inserted: list[tuple[str, tuple[Any, ...]]] = []

    class Db:
        async def fetchval(self, query: str, *args: Any) -> UUID:
            inserted.append((query, args))
            return uuid4()

    await clustering._create_area(Db(), 14.5547, 120.9975, 3, 2, None)  # type: ignore[arg-type]
    (query, args), = inserted
    assert "area_code" in query and "place_street" in query
    assert args[:5] == (CORNER, "Area 3.2", "Taft Avenue", "Gil Puyat Avenue", None)


async def test_before_the_migration_a_fire_is_still_reported_by_its_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backend can go live before 20261119120000_street_names.sql is
    applied: the new columns are missing, so the area is made as before."""

    async def unnamed(db: Any, lat: float, lng: float, *, leave_out: UUID | None = None) -> Place:
        return Place()

    monkeypatch.setattr(clustering, "find_place", unnamed)
    inserted: list[tuple[str, tuple[Any, ...]]] = []

    class Db:
        async def fetchval(self, query: str, *args: Any) -> UUID:
            inserted.append((query, args))
            if "area_code" in query:
                raise asyncpg.exceptions.UndefinedColumnError(
                    'column "area_code" of relation "areas" does not exist'
                )
            return uuid4()

    await clustering._create_area(Db(), 14.5, 121.0, 7, 1, None)  # type: ignore[arg-type]
    assert len(inserted) == 2
    query, args = inserted[1]
    assert "area_code" not in query
    assert args[:3] == ("Area 7", 7, 1)


# --------------------------------------------------------------------------- #
# The number, kept for the PDF report alone
# --------------------------------------------------------------------------- #
def test_the_pdf_report_keeps_the_area_number_as_its_reference() -> None:
    facts = {**_facts(), "designation": NEAR, "area_code": "Area 3.2"}
    text = build_fire_out_pdf(facts, None, compress=False).decode("latin-1")
    assert "Near F. Victor Street" in text
    assert "Reference" in text and "Area 3.2" in text


# --------------------------------------------------------------------------- #
# The far-fire voice
# --------------------------------------------------------------------------- #
def test_the_far_voice_is_for_app_1_12_51_and_later() -> None:
    assert FAR_VOICE_SINCE == (1, 12, 53)
    assert has_far_voice("1.12.53 (80)") and has_far_voice("1.13.0")
    assert not has_far_voice("1.12.52")
    assert not has_far_voice(None) and not has_far_voice("dev")
    assert (far_voice("tl"), far_voice("en")) == ("far_tl", "far_en")


def test_the_far_voice_plays_its_own_file_on_its_own_channel() -> None:
    for language, channel in (("en", "citizen_far_en_v1"), ("tl", "citizen_far_tl_v1")):
        config = android_config(sound=far_voice(language), modern=True)
        assert config.notification is not None
        assert config.notification.channel_id == channel == SOUND_CHANNELS_V2[far_voice(language)]
        assert config.notification.sound == f"sound_far_{language}"
    # The 100 m alert keeps its recording.
    assert SOUND_CHANNELS_V2["citizen"] == "citizen_nearby_v1"
