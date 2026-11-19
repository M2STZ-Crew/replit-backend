"""Name the fires recorded before v1.12.42 after their streets.

    python scripts/name_areas.py --dry-run
    python scripts/name_areas.py

An Area made before v1.12.42 is still called by its number ("Area 3.2"). This
names each one the way a new Area is named (app/services/place_names.py),
from the streets around its centre: "Taft Avenue corner Gil Puyat Avenue",
"Near F. Victor Street". Its number stays in area_code, where the migration
put it, for the PDF report. Run after scripts/load_streets.py.

Only Areas still called by their number are named, oldest first, so running
it again names nothing twice. A live fire that would share its name with
another live one gets " (2)". --dry-run prints each new name and writes
nothing. Run from the folder whose .env points at the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import Database  # noqa: E402
from app.services.place_names import find_place, place_name  # noqa: E402


async def name_all(dry_run: bool) -> int:
    db = Database()
    await db.connect()
    try:
        streets = await db.fetchval("select count(*) from public.streets")
        if not streets:
            print("public.streets is empty: load the streets first (scripts/load_streets.py).")
            return 1
        areas = await db.fetch(
            """
            select id, designation, area_code, centroid_lat, centroid_lng
              from public.areas
             where place_street is null
               and designation = coalesce(area_code, designation)
             order by reported_at nulls first, created_at
            """
        )
        print(f"Areas still called by their number: {len(areas)}")
        named = unnamed = 0
        for area in areas:
            lat, lng = float(area["centroid_lat"]), float(area["centroid_lng"])
            place = await find_place(db, lat, lng, leave_out=area["id"])
            name = place_name(place, lat, lng)
            if place.street:
                named += 1
            else:
                unnamed += 1
            print(f"  {area['area_code'] or area['designation']}: {name}")
            if dry_run:
                continue
            await db.execute(
                """
                update public.areas
                   set designation = $2,
                       area_code = coalesce(area_code, $3),
                       place_street = $4, place_cross = $5, place_number = $6
                 where id = $1
                """,
                area["id"],
                name,
                area["designation"],
                place.street,
                place.cross,
                place.number,
            )
        print(f"named after a street: {named}; by coordinates (no street near): {unnamed}")
        if dry_run:
            print("dry run: nothing written")
    finally:
        await db.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the names; write nothing")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return asyncio.run(name_all(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
