"""Fires named after their streets (v1.12.42).

18 November 2026: "instead of area, it will be called 'Near [street]' or the
street itself because 'Area #1' is not appropriate or overwhelming to citizens
and to all ... '[street] corner [street]' or 'near [street]'". Answered:
"Corner, else Near", and the area number "Nowhere on screen".

A new Area is named from the OpenStreetMap streets around its first report
(public.streets, loaded by scripts/load_streets.py; docs/data-sources.md):

- "Taft Avenue corner Gil Puyat Avenue" when two named streets meet within
  CORNER_RADIUS_M of it, the nearer street first;
- else "Near F. Victor Street", the nearest named street within
  NEAR_RADIUS_M, or failing that FAR_RADIUS_M;
- else its coordinates, "14.5378° N, 121.0014° E", as the console shows a
  place it cannot name.

A live fire that would share its name with another gets " (2)", " (3)" ...

The name is kept in areas.designation, so every screen, alert, summary and
report says it; the number ("Area 3.2") stays in areas.area_code, for the PDF
report's reference only. Tagalog says "Malapit sa F. Victor Street"
(in_language); a corner reads the same in both languages, the way Metro
Manila says it ("Taft corner Buendia").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.services.incident import active_area_sql

log = get_logger(__name__)

# The same languages as app/services/citizen_copy.py, which reads this module.
Language = Literal["en", "tl"]

# The answer's own words: "within about 30 m of where two streets meet".
CORNER_RADIUS_M = 30.0
NEAR_RADIUS_M = 300.0
FAR_RADIUS_M = 1500.0
# Two ways meet where they come this close. OpenStreetMap's ways share a node
# at a junction (0 m); a few are drawn a little apart.
MEET_M = 3.0

NEAR = "Near "
CORNER = " corner "

# The point, in the streets' projection (UTM zone 51N, metres).
_POINT_SQL = """
p as (
    select extensions.ST_Transform(
               extensions.ST_SetSRID(extensions.ST_MakePoint($2, $1), 4326), 32651) as g
)"""

# Two differently named streets that meet within $3 m of the point, the
# junction nearest the point first and, of the pair, the nearer street first.
_CORNER_SQL = f"""
with {_POINT_SQL},
near as (
    select s.name, s.geom, extensions.ST_Distance(s.geom, p.g) as d
      from public.streets s, p
     where extensions.ST_DWithin(s.geom, p.g, $3)
)
select a.name as street, b.name as cross_street
  from near a
  join near b on b.name <> a.name
 cross join p
 where extensions.ST_DWithin(a.geom, b.geom, $4)
   and extensions.ST_DWithin(extensions.ST_ClosestPoint(a.geom, b.geom), p.g, $3)
 order by extensions.ST_Distance(extensions.ST_ClosestPoint(a.geom, b.geom), p.g), a.d, b.d
 limit 1
"""

# The nearest named street within $3 m.
_NEAR_SQL = f"""
with {_POINT_SQL}
select s.name
  from public.streets s, p
 where extensions.ST_DWithin(s.geom, p.g, $3)
 order by extensions.ST_Distance(s.geom, p.g)
 limit 1
"""

# The highest number among the live fires already called this ($3: one to
# leave out, when an Area is named again). A fire with no number counts as 1.
_TAKEN_SQL = f"""
select max(coalesce(place_number, 1))
  from public.areas
 where {active_area_sql()}
   and place_street = $1
   and place_cross is not distinct from $2
   and ($3::uuid is null or id <> $3::uuid)
"""


@dataclass(frozen=True)
class Place:
    """What a fire is named after: a street, the street it meets at a corner,
    and its number among live fires of the same name. No street: unnamed."""

    street: str | None = None
    cross: str | None = None
    number: int | None = None


def degrees(lat: float, lng: float) -> str:
    """ "14.5378° N, 121.0014° E", as the console writes a place (lib/place.js)."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lng >= 0 else "W"
    return f"{abs(lat):.4f}° {ns}, {abs(lng):.4f}° {ew}"


def place_name(place: Place, lat: float, lng: float) -> str:
    """The English name: "Taft Avenue corner Gil Puyat Avenue", "Near F. Victor
    Street", "Near F. Victor Street (2)", or the coordinates."""
    if not place.street:
        return degrees(lat, lng)
    base = f"{place.street}{CORNER}{place.cross}" if place.cross else f"{NEAR}{place.street}"
    return f"{base} ({place.number})" if place.number else base


def in_language(designation: str | None, language: Language) -> str:
    """The name as the reader says it: "Malapit sa F. Victor Street" in Tagalog.
    A corner, coordinates and an older Area's number read the same in both."""
    text = (designation or "").strip()
    if language == "tl" and text.startswith(NEAR):
        return "Malapit sa " + text[len(NEAR) :]
    return text


def where(designation: str | None, language: Language) -> str:
    """The name inside a sentence: "near F. Victor Street", "at Taft Avenue
    corner Gil Puyat Avenue"; in Tagalog "malapit sa ...", "sa ...". Empty
    when the fire has no name."""
    text = (designation or "").strip()
    if not text:
        return ""
    if text.startswith(NEAR):
        street = text[len(NEAR) :]
        return f"malapit sa {street}" if language == "tl" else f"near {street}"
    return f"sa {text}" if language == "tl" else f"at {text}"


async def find_place(
    db: Database, lat: float, lng: float, *, leave_out: UUID | None = None
) -> Place:
    """Name a fire at ([lat], [lng]) from the streets around it. Never raises:
    with no streets loaded, or a lookup that fails, the fire is unnamed and is
    called by its coordinates rather than not reported. [leave_out] is the
    Area itself when one is named again."""
    try:
        corner = await db.fetchrow(_CORNER_SQL, lat, lng, CORNER_RADIUS_M, MEET_M)
        if corner is not None:
            street, cross = str(corner["street"]), str(corner["cross_street"])
        else:
            near = None
            for radius in (NEAR_RADIUS_M, FAR_RADIUS_M):
                near = await db.fetchrow(_NEAR_SQL, lat, lng, radius)
                if near is not None:
                    break
            if near is None:
                return Place()
            street, cross = str(near["name"]), None
        taken = await db.fetchval(_TAKEN_SQL, street, cross, leave_out)
    except Exception:
        log.warning("place_lookup_failed", lat=lat, lng=lng, exc_info=True)
        return Place()
    number = int(taken) + 1 if taken is not None else None
    return Place(street, cross, number)
