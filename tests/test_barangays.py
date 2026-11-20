"""v1.12.45: a fire is named in its barangay, and the barangay layer.

19 Nov 2026: "Concha Street corner Camba Street, Barangay 70 Zone 10, Tondo,
Manila ... we are covering metro manila for now"; the full form in details,
the short in alerts. And "barangay map outline ... displayed as a clean layer
so you can color-code and highlight fire risk zones", with Pasay's eight High
zones, research-based, never a BFP designation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import map_layers
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import clustering, place_names
from app.services.place_names import (
    Barangay,
    Place,
    find_place,
    in_language,
    place_line,
    place_name,
    short_street,
    where,
)
from scripts.load_barangays import DATA, check, read

TONDO_70 = Barangay("PH1303901070", "Barangay 70", "numbered", "70", 6, "Tondo", "Manila")
PASAY_76 = Barangay("PH1307605076", "Barangay 76", "numbered", "76", 10, None, "Pasay")
BEL_AIR = Barangay("PH1307602003", "Bel-Air", "named", None, None, None, "Makati")
LAT, LNG = 14.5378, 121.0014


@pytest.mark.parametrize(
    ("place", "short", "full"),
    [
        (
            Place("Concha Street", "Camba Street", None, TONDO_70),
            "Concha St. corner Camba St., Brgy 70, Tondo",
            "Concha Street corner Camba Street, Barangay 70 Zone 6, Tondo, Manila",
        ),
        (
            Place("F. Victor Street", None, None, PASAY_76),
            "Near F. Victor St., Brgy 76, Pasay",
            "Near F. Victor Street, Barangay 76 Zone 10, Pasay",
        ),
        (
            Place("Ayala Avenue", "Paseo de Roxas", None, BEL_AIR),
            "Ayala Ave. corner Paseo de Roxas, Bel-Air, Makati",
            "Ayala Avenue corner Paseo de Roxas, Bel-Air, Makati",
        ),
        (
            Place("F. Victor Street", None, 2, PASAY_76),
            "Near F. Victor St., Brgy 76, Pasay (2)",
            "Near F. Victor Street, Barangay 76 Zone 10, Pasay (2)",
        ),
        # No street within 1.5 km, in a barangay: the barangay alone.
        (Place(barangay=PASAY_76), "Brgy 76, Pasay", "Barangay 76 Zone 10, Pasay"),
        # Outside Metro Manila, or before the barangays: v1.12.42's name.
        (
            Place("Taft Avenue", "Gil Puyat Avenue"),
            "Taft Avenue corner Gil Puyat Avenue",
            "Taft Avenue corner Gil Puyat Avenue",
        ),
    ],
)
def test_the_short_name_for_alerts_and_the_full_place_for_details(
    place: Place, short: str, full: str
) -> None:
    assert place_name(place, LAT, LNG) == short
    assert place_line(place, LAT, LNG) == full


def test_only_a_streets_last_word_is_shortened() -> None:
    assert short_street("Taft Avenue Extension") == "Taft Ave. Ext."
    assert short_street("Roxas Boulevard") == "Roxas Blvd."
    assert short_street("EDSA") == "EDSA"
    assert short_street("Avenue") == "Avenue"
    assert short_street("Paseo de Roxas") == "Paseo de Roxas"


def test_tagalog_and_sentences_read_the_short_name() -> None:
    short = "Near F. Victor St., Brgy 76, Pasay"
    assert in_language(short, "tl") == "Malapit sa F. Victor St., Brgy 76, Pasay"
    assert where(short, "en") == "near F. Victor St., Brgy 76, Pasay"
    assert where("Concha St. corner Camba St., Brgy 70, Tondo", "tl") == (
        "sa Concha St. corner Camba St., Brgy 70, Tondo"
    )


class _PlacesDb:
    """Answers the barangay, corner, near and taken lookups."""

    def __init__(
        self,
        *,
        barangay: dict[str, Any] | None = None,
        corner: dict[str, str] | None = None,
        near: dict[str, str] | None = None,
        no_barangays: bool = False,
    ) -> None:
        self.barangay = barangay
        self.corner = corner
        self.near = near
        self.no_barangays = no_barangays
        self.taken: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.barangays" in query:
            if self.no_barangays:
                raise asyncpg.exceptions.UndefinedTableError(
                    'relation "public.barangays" does not exist'
                )
            assert args[2] == place_names.BARANGAY_RADIUS_M
            return self.barangay
        if "join near b" in query:
            return self.corner
        return self.near

    async def fetchval(self, query: str, *args: Any) -> int | None:
        self.taken.append((query, args))
        return None


_PASAY_ROW = {
    "pcode": "PH1307605076", "name": "Barangay 76", "kind": "numbered", "number": "76",
    "zone": 10, "district": None, "city": "Pasay",
}


async def test_a_fire_is_named_in_the_barangay_it_is_in() -> None:
    db = _PlacesDb(barangay=_PASAY_ROW, near={"name": "F. Victor Street"})
    place = await find_place(db, LAT, LNG)  # type: ignore[arg-type]
    assert place == Place("F. Victor Street", None, None, PASAY_76)
    # "(2)" counts the same street in the same barangay only.
    (query, args), = db.taken
    assert "barangay_pcode = $4" in query
    assert args == ("F. Victor Street", None, None, "PH1307605076")


async def test_with_no_street_near_a_fire_in_a_barangay_is_named_by_it() -> None:
    db = _PlacesDb(barangay=_PASAY_ROW)
    place = await find_place(db, LAT, LNG)  # type: ignore[arg-type]
    assert place == Place(None, None, None, PASAY_76)
    assert place_name(place, LAT, LNG) == "Brgy 76, Pasay"


async def test_before_the_barangays_the_fire_is_named_as_before() -> None:
    db = _PlacesDb(near={"name": "F. Victor Street"}, no_barangays=True)
    place = await find_place(db, LAT, LNG)  # type: ignore[arg-type]
    assert place == Place("F. Victor Street")
    assert place_name(place, LAT, LNG) == "Near F. Victor Street"
    (query, _), = db.taken
    assert "barangay_pcode" not in query


@pytest.mark.parametrize("barangay", [PASAY_76, None])
async def test_a_new_area_keeps_its_full_place_and_barangay(
    monkeypatch: pytest.MonkeyPatch, barangay: Barangay | None
) -> None:
    async def placed(db: Any, lat: float, lng: float, *, leave_out: UUID | None = None) -> Place:
        return Place("F. Victor Street", None, None, barangay)

    monkeypatch.setattr(clustering, "find_place", placed)
    inserted: list[tuple[str, tuple[Any, ...]]] = []

    class Db:
        async def fetchval(self, query: str, *args: Any) -> UUID:
            inserted.append((query, args))
            return uuid4()

    await clustering._create_area(Db(), LAT, LNG, 3, 1, None)  # type: ignore[arg-type]
    (query, args), = inserted
    if barangay is None:
        assert "place_line" not in query
        assert args[0] == "Near F. Victor Street"
    else:
        assert "place_line, barangay_pcode" in query
        assert args[0] == "Near F. Victor St., Brgy 76, Pasay"
        assert args[-2:] == ("Near F. Victor Street, Barangay 76 Zone 10, Pasay", PASAY_76.pcode)


# --------------------------------------------------------------------------- #
# The layer
# --------------------------------------------------------------------------- #
class _LayerDb:
    def __init__(self, missing: bool = False) -> None:
        self.missing = missing

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if self.missing:
            raise asyncpg.exceptions.UndefinedTableError(
                'relation "public.barangays" does not exist'
            )
        outline = json.dumps({"type": "MultiPolygon", "coordinates": []})
        return [
            {
                "pcode": "PH1307605076", "name": "Barangay 76", "kind": "numbered",
                "number": "76", "zone": 10, "district": None, "city": "Pasay",
                "area_geojson": outline, "risk_zone": None, "risk_level": None,
                "risk_source": None, "assessment_start": None, "assessment_end": None,
            },
            {
                "pcode": "PH1307605183", "name": "Barangay 183", "kind": "numbered",
                "number": "183", "zone": 20, "district": None, "city": "Pasay",
                "area_geojson": outline, "risk_zone": 20, "risk_level": "High",
                "risk_source": "RepLiT research-based fire incident assessment",
                "assessment_start": date(2022, 1, 1), "assessment_end": date(2026, 11, 19),
            },
        ]


@pytest.fixture
def layer_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setitem(map_layers._layer, "at", 0.0)
    settings = get_settings()
    monkeypatch.setattr(settings, "require_citizen_email_verification", False)
    monkeypatch.setattr(settings, "require_citizen_phone_verification", False)
    resident = AuthenticatedUser(id=uuid4(), role="general_user")
    app.dependency_overrides[get_current_user] = lambda: resident
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_everyone_gets_the_layer_gzipped_with_the_high_zones_labelled(
    layer_client: TestClient,
) -> None:
    app.dependency_overrides[get_database] = lambda: _LayerDb()
    response = layer_client.get("/map/barangays", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    plain, high = response.json()  # the client unpacks it
    assert (plain["name"], plain["zone"], plain["risk"]) == ("Barangay 76", 10, None)
    assert high["risk"] == {
        "zone_id": 20,
        "level": "High",
        "label": "High fire-risk zone (research-based)",
        "source": "RepLiT research-based fire incident assessment",
        "assessment_start": "2022-01-01",
        "assessment_end": "2026-11-19",
        "official_bfp_designation": False,
    }
    unpacked = layer_client.get("/map/barangays", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in unpacked.headers
    assert len(unpacked.json()) == 2


def test_before_its_migration_the_layer_is_empty(layer_client: TestClient) -> None:
    app.dependency_overrides[get_database] = lambda: _LayerDb(missing=True)
    response = layer_client.get("/map/barangays")
    assert response.status_code == 200
    assert response.json() == []
    # Not kept: the next call looks again, so the layer appears once loaded.
    assert map_layers._layer["at"] == 0.0


# --------------------------------------------------------------------------- #
# The data
# --------------------------------------------------------------------------- #
def test_the_files_hold_metro_manilas_barangays_and_eight_high_zones() -> None:
    barangays, risk = read(DATA)
    assert check(barangays, risk) == []
    assert len(barangays) == 1712 and len(risk) == 86
    by_code = {b["pcode"]: b for b in barangays}
    assert {r["zone_id"] for r in risk} == {8, 11, 13, 14, 15, 16, 19, 20}
    assert all(by_code[r["pcode"]]["city"] == "Pasay" for r in risk)
    assert all(r["risk_level"] == "High" and not r["official_bfp_designation"] for r in risk)
    # Every numbered barangay has its zone; Manila's have their district.
    assert all(b["zone"] for b in barangays if b["kind"] == "numbered")
    assert all(b["district"] for b in barangays if b["city"] == "Manila")
    assert by_code["PH1307605076"]["zone"] == 10
