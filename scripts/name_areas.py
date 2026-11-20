"""Name the fires recorded before v1.12.42 after their streets, and (v1.12.45)
add the barangay to the names of fires named before it.

    python scripts/name_areas.py --dry-run
    python scripts/name_areas.py
    python scripts/name_areas.py --barangays --dry-run
    python scripts/name_areas.py --barangays

An Area made before v1.12.42 is still called by its number ("Area 3.2"). This
names each one the way a new Area is named (app/services/place_names.py),
from the streets and barangay around its centre: "Near F. Victor St., Brgy
76, Pasay", with the full place "Near F. Victor Street, Barangay 76 Zone 10,
Pasay". Its number stays in area_code, where the migration put it, for the
PDF report. Run after scripts/load_streets.py (and scripts/load_barangays.py).

--barangays also names again the Areas already named after their streets but
not their barangay (v1.12.42 to v1.12.44): "Near F. Victor Street" becomes
"Near F. Victor St., Brgy 76, Pasay". Needs migration 20261120150000 and the
barangays loaded.

Areas are taken oldest first, so running it again names nothing twice. A live
fire that would share its name with another live one gets " (2)". --dry-run
prints each new name and writes nothing. Run from the folder whose .env
points at the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import Database  # noqa: E402
from app.services.place_names import find_place, place_line, place_name  # noqa: E402

_BY_NUMBER = "place_street is null and designation = coalesce(area_code, designation)"


async def _barangays_loaded(db: Database) -> bool:
    try:
        return bool(await db.fetchval("select count(*) from public.barangays"))
    except Exception:
        return False


async def name_all(dry_run: bool, barangays: bool) -> int:
    db = Database()
    await db.connect()
    try:
        streets = await db.fetchval("select count(*) from public.streets")
        if not streets:
            print("public.streets is empty: load the streets first (scripts/load_streets.py).")
            return 1
        loaded = await _barangays_loaded(db)
        if barangays and not loaded:
            print(
                "No barangays: apply migration 20261120150000 and run "
                "scripts/load_barangays.py first."
            )
            return 1
        which = f"({_BY_NUMBER}) or barangay_pcode is null" if barangays else _BY_NUMBER
        areas = await db.fetch(
            f"""
            select id, designation, area_code, centroid_lat, centroid_lng
              from public.areas
             where {which}
             order by reported_at nulls first, created_at
            """
        )
        print(f"Areas to name: {len(areas)}")
        in_barangay = by_street = unnamed = 0
        for area in areas:
            lat, lng = float(area["centroid_lat"]), float(area["centroid_lng"])
            place = await find_place(db, lat, lng, leave_out=area["id"])
            name = place_name(place, lat, lng)
            line = place_line(place, lat, lng)
            if place.barangay is not None:
                in_barangay += 1
            elif place.street:
                by_street += 1
            else:
                unnamed += 1
            print(f"  {area['designation']}: {name}  |  {line}")
            if dry_run:
                continue
            if loaded:
                await db.execute(
                    """
                    update public.areas
                       set designation = $2,
                           area_code = coalesce(area_code, $3),
                           place_street = $4, place_cross = $5, place_number = $6,
                           place_line = $7, barangay_pcode = $8
                     where id = $1
                    """,
                    area["id"],
                    name,
                    area["designation"],
                    place.street,
                    place.cross,
                    place.number,
                    line if place.barangay is not None else None,
                    place.barangay.pcode if place.barangay is not None else None,
                )
            else:
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
        print(
            f"in a barangay: {in_barangay}; after a street only: {by_street}; "
            f"by coordinates (nothing near): {unnamed}"
        )
        if dry_run:
            print("dry run: nothing written")
    finally:
        await db.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the names; write nothing")
    parser.add_argument(
        "--barangays",
        action="store_true",
        help="also name again the Areas named before the barangays (v1.12.42 to v1.12.44)",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return asyncio.run(name_all(args.dry_run, args.barangays))


if __name__ == "__main__":
    raise SystemExit(main())
