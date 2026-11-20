"""Load Metro Manila's barangays and Pasay's High fire-risk zones (v1.12.45).

    python scripts/load_barangays.py --dry-run
    python scripts/load_barangays.py

Reads docs/barangays/:

- ncr-barangays-psa.geojson.gz: PSA/NAMRIA's 1,712 barangay outlines (UN OCHA
  COD-AB v03, layer phl_admin4, valid 13 February 2025; CC BY-IGO 3.0);
- metro-manila-barangays.csv: each barangay's name, kind, number, zone,
  Manila district and city, joined by PSGC code (zones and districts from
  Wikipedia, CC BY-SA 4.0);
- pasay-high-fire-risk-barangays.csv: the 86 barangays of Pasay's Zones 8,
  11, 13, 14, 15, 16, 19 and 20, High, from RepLiT's research-based
  assessment (never a BFP designation).

docs/data-sources.md cites each. Fires are named in their barangay
(app/services/place_names.py) and the outlines are a map layer (GET
/map/barangays). Rows are matched by PSGC code, so loading again updates in
place. --dry-run checks the files and writes nothing. Needs migration
20261120150000_barangays.sql. Run from the folder whose .env points at the
database.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import Database  # noqa: E402

DATA = ROOT / "docs" / "barangays"
_BATCH = 100
# Metro Manila's barangays, by PSGC's count.
EXPECTED = 1712

_UPSERT = """
insert into public.barangays
    (pcode, psa_name, name, kind, number, zone, district, city, city_pcode, geom, geom_map)
select t.pcode, t.psa_name, t.name, t.kind, t.number, t.zone, t.district, t.city, t.city_pcode,
       g.utm,
       extensions.ST_Multi(extensions.ST_CollectionExtract(extensions.ST_Transform(
           extensions.ST_SimplifyPreserveTopology(g.utm, 2), 4326), 3))
  from unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::text[], $6::int[],
              $7::text[], $8::text[], $9::text[], $10::text[])
       as t(pcode, psa_name, name, kind, number, zone, district, city, city_pcode, gj)
 cross join lateral (
     select extensions.ST_Multi(extensions.ST_CollectionExtract(extensions.ST_MakeValid(
                extensions.ST_Transform(
                    extensions.ST_SetSRID(extensions.ST_GeomFromGeoJSON(t.gj), 4326), 32651)), 3))
            as utm
 ) g
on conflict (pcode) do update
   set psa_name = excluded.psa_name, name = excluded.name, kind = excluded.kind,
       number = excluded.number, zone = excluded.zone, district = excluded.district,
       city = excluded.city, city_pcode = excluded.city_pcode,
       geom = excluded.geom, geom_map = excluded.geom_map
"""

_UPSERT_RISK = """
insert into public.fire_risk_barangays
    (pcode, zone_id, barangay_no, risk_level, risk_source,
     assessment_start, assessment_end, official_bfp_designation)
select * from unnest($1::text[], $2::int[], $3::text[], $4::text[], $5::text[],
                     $6::date[], $7::date[], $8::boolean[])
on conflict (pcode) do update
   set zone_id = excluded.zone_id, barangay_no = excluded.barangay_no,
       risk_level = excluded.risk_level, risk_source = excluded.risk_source,
       assessment_start = excluded.assessment_start,
       assessment_end = excluded.assessment_end,
       official_bfp_designation = excluded.official_bfp_designation
"""


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def read(data: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The barangays (with their outlines) and the High fire-risk rows."""
    with gzip.open(data / "ncr-barangays-psa.geojson.gz", "rt", encoding="utf-8") as f:
        features = json.load(f)["features"]
    outlines = {f["properties"]["adm4_pcode"]: f["geometry"] for f in features}
    with open(data / "metro-manila-barangays.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    barangays = []
    for r in rows:
        geometry = outlines.get(r["pcode"])
        if geometry is None:
            raise SystemExit(f"no outline for {r['pcode']} ({r['name']})")
        barangays.append(
            {
                "pcode": r["pcode"],
                "psa_name": r["psa_name"],
                "name": r["name"],
                "kind": r["kind"],
                "number": _text(r["number"]),
                "zone": int(r["zone"]) if _text(r["zone"]) else None,
                "district": _text(r["district"]),
                "city": r["city"],
                "city_pcode": r["city_pcode"],
                "gj": json.dumps(geometry),
            }
        )
    with open(data / "pasay-high-fire-risk-barangays.csv", encoding="utf-8", newline="") as f:
        risk = [
            {
                "pcode": r["pcode"],
                "zone_id": int(r["zone_id"]),
                "barangay_no": r["barangay_no"],
                "risk_level": r["risk_level"],
                "risk_source": r["risk_source"],
                "assessment_start": date.fromisoformat(r["assessment_start"]),
                "assessment_end": date.fromisoformat(r["assessment_end"]),
                "official_bfp_designation": r["official_bfp_designation"].lower() == "true",
            }
            for r in csv.DictReader(f)
        ]
    return barangays, risk


def check(barangays: list[dict[str, Any]], risk: list[dict[str, Any]]) -> list[str]:
    """What is wrong with the files, if anything."""
    problems = []
    if len(barangays) != EXPECTED:
        problems.append(f"{len(barangays)} barangays, not {EXPECTED}")
    known = {b["pcode"] for b in barangays}
    if len(known) != len(barangays):
        problems.append("a PSGC code appears twice")
    for r in risk:
        if r["pcode"] not in known:
            problems.append(f"risk row {r['pcode']} has no barangay")
        if r["risk_level"] != "High" or r["official_bfp_designation"]:
            problems.append(f"risk row {r['pcode']} is not a research-based High zone")
    return problems


async def load(dry_run: bool) -> int:
    barangays, risk = read(DATA)
    print(f"barangays: {len(barangays)}; High fire-risk rows: {len(risk)}")
    for city, count in sorted(Counter(b["city"] for b in barangays).items()):
        print(f"  {city}: {count}")
    print(f"High zones: {sorted({r['zone_id'] for r in risk})}")
    problems = check(barangays, risk)
    if problems:
        print("Nothing written:")
        for p in problems:
            print(f"  {p}")
        return 1
    if dry_run:
        print("dry run: nothing written")
        return 0

    db = Database()
    await db.connect()
    try:
        async with db.acquire() as conn, conn.transaction():
            for start in range(0, len(barangays), _BATCH):
                batch = barangays[start : start + _BATCH]
                await conn.execute(_UPSERT, *[[b[k] for b in batch] for k in (
                    "pcode", "psa_name", "name", "kind", "number", "zone",
                    "district", "city", "city_pcode", "gj",
                )])
            await conn.execute(_UPSERT_RISK, *[[r[k] for r in risk] for k in (
                "pcode", "zone_id", "barangay_no", "risk_level", "risk_source",
                "assessment_start", "assessment_end", "official_bfp_designation",
            )])
        print(
            "public.barangays now holds",
            await db.fetchval("select count(*) from public.barangays"),
        )
        print(
            "public.fire_risk_barangays now holds",
            await db.fetchval("select count(*) from public.fire_risk_barangays"),
        )
        print(
            "vertices for the map:",
            await db.fetchval("select sum(extensions.ST_NPoints(geom_map)) from public.barangays"),
        )
    finally:
        await db.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="check the files; write nothing")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return asyncio.run(load(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
