"""Load Metro Manila's named streets into public.streets (v1.12.40).

    python scripts/load_streets.py ncr_streets.json --dry-run
    python scripts/load_streets.py ncr_streets.json
    python scripts/load_streets.py ncr_streets.json --prune

The file is an Overpass answer (out geom) for the named streets of Metro
Manila, ISO 3166-2 PH-00; docs/data-sources.md gives the query. New Areas are
named from these (app/services/place_names.py): "Taft Avenue corner Gil Puyat
Avenue", "Near F. Victor Street".

Bridges, flyovers and tunnels are left out: a fire beneath a flyover is on the
street below, and a flyover would make a corner where none is. A way is
matched by its OpenStreetMap id, so loading a newer file updates the streets
in place and nothing is doubled; --prune also removes the ways the new file no
longer has. --dry-run says what it would load and writes nothing.

The data is (c) OpenStreetMap contributors, under the Open Database License.
Run from the folder whose .env points at the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import Database  # noqa: E402

# Streets people name a place by (the query asks for these alone).
KINDS = {
    "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
    "pedestrian", "road",
}
_BATCH = 2000

_UPSERT = """
insert into public.streets (osm_id, name, kind, geom)
select o, n, k, extensions.ST_Transform(extensions.ST_GeomFromText(w, 4326), 32651)
  from unnest($1::bigint[], $2::text[], $3::text[], $4::text[]) as t(o, n, k, w)
on conflict (osm_id) do update
   set name = excluded.name, kind = excluded.kind, geom = excluded.geom
"""


def streets_of(elements: list[dict[str, Any]]) -> list[tuple[int, str, str, str]]:
    """(osm id, name, kind, WKT line) for each way worth naming a fire after."""
    kept: list[tuple[int, str, str, str]] = []
    for e in elements:
        tags = e.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        kind = str(tags.get("highway") or "")
        points = e.get("geometry") or []
        if e.get("type") != "way" or not name or kind not in KINDS or len(points) < 2:
            continue
        if tags.get("bridge", "no") != "no" or tags.get("tunnel", "no") != "no":
            continue
        if tags.get("layer", "0").lstrip("-").isdigit() and int(tags.get("layer", "0")) != 0:
            continue
        line = ", ".join(f"{p['lon']} {p['lat']}" for p in points)
        kept.append((int(e["id"]), name, kind, f"LINESTRING({line})"))
    return kept


async def load(answer: dict[str, Any], dry_run: bool, prune: bool) -> int:
    elements = answer.get("elements") or []
    streets = streets_of(elements)
    print(f"ways in the file: {len(elements)}; to load: {len(streets)}")
    print(f"OpenStreetMap data as of: {answer.get('osm3s', {}).get('timestamp_osm_base')}")
    for kind, count in Counter(s[2] for s in streets).most_common():
        print(f"  {kind}: {count}")
    print(f"distinct names: {len({s[1] for s in streets})}")
    if len(streets) < 1000:
        print("Fewer than 1,000 streets: a cut-off download? Nothing written.")
        return 1
    if dry_run:
        print("dry run: nothing written")
        return 0

    db = Database()
    await db.connect()
    try:
        async with db.acquire() as conn, conn.transaction():
            for start in range(0, len(streets), _BATCH):
                batch = streets[start : start + _BATCH]
                await conn.execute(
                    _UPSERT,
                    [s[0] for s in batch],
                    [s[1] for s in batch],
                    [s[2] for s in batch],
                    [s[3] for s in batch],
                )
            if prune:
                gone = await conn.execute(
                    "delete from public.streets where osm_id <> all($1::bigint[])",
                    [s[0] for s in streets],
                )
                print(f"pruned: {gone}")
        total = await db.fetchval("select count(*) from public.streets")
        print(f"public.streets now holds {total} ways")
    finally:
        await db.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", type=Path, help="the Overpass answer (JSON, out geom)")
    parser.add_argument("--dry-run", action="store_true", help="say what would load; write nothing")
    parser.add_argument("--prune", action="store_true", help="remove ways the file no longer has")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    answer = json.loads(args.file.read_text(encoding="utf-8"))
    return asyncio.run(load(answer, args.dry_run, args.prune))


if __name__ == "__main__":
    raise SystemExit(main())
