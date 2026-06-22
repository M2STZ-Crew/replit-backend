"""Area clustering service (Section 3.4).

Assigns each new report to an area:
  1. an active cluster within 300 m whose activity is < 5 min old  -> match,
  2. else a same-location area (within 300 m) updated < 1 hour ago -> new version
     (Area 1.2, 1.3 ...),
  3. else a brand-new area.
On every change it recomputes the centroid (arithmetic mean) and the confidence
score 0.4*N + 0.3*S + 0.3*V. Spatial proximity uses PostGIS (schema-qualified so it
works through the transaction pooler regardless of search_path); centroid/spread
use Python.
"""

from __future__ import annotations

import statistics
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.services.geo import haversine_m

log = get_logger(__name__)

_CLUSTER_RADIUS_M = 300
_RECENT_WINDOW = "5 minutes"
_VERSION_WINDOW = "1 hour"


def _designation(base_number: int, version: int) -> str:
    """Human-readable area label: 'Area 1' (v1) or 'Area 1.2' (v2)."""
    return f"Area {base_number}" if version <= 1 else f"Area {base_number}.{version}"


async def cluster_report(db: Database, *, report_id: UUID, lat: float, lng: float) -> UUID:
    """Cluster a report into an area (match / version / new); return the area id."""
    point = f"SRID=4326;POINT({lng} {lat})"

    # 1) Active cluster within 300 m, active in the last 5 minutes.
    match = await db.fetchrow(
        f"""
        select id from public.areas
        where status not in ('resolved', 'rejected')
          and extensions.ST_DWithin(
                centroid, extensions.ST_GeographyFromText($1), {_CLUSTER_RADIUS_M})
          and updated_at > now() - interval '{_RECENT_WINDOW}'
        order by extensions.ST_Distance(centroid, extensions.ST_GeographyFromText($1))
        limit 1
        """,
        point,
    )
    if match is not None:
        area_id: UUID = match["id"]
        await _attach_and_recompute(db, area_id, report_id)
        log.info("report_clustered", area_id=str(area_id), mode="match")
        return area_id

    # 2) Same-location area updated within the last hour -> a new version.
    version_src = await db.fetchrow(
        f"""
        select id, base_number from public.areas
        where extensions.ST_DWithin(
                centroid, extensions.ST_GeographyFromText($1), {_CLUSTER_RADIUS_M})
          and base_number is not null
          and updated_at > now() - interval '{_VERSION_WINDOW}'
        order by updated_at desc
        limit 1
        """,
        point,
    )
    if version_src is not None:
        base = int(version_src["base_number"])
        next_version = int(
            await db.fetchval(
                "select coalesce(max(version), 0) + 1 from public.areas where base_number = $1",
                base,
            )
        )
        area_id = await _create_area(db, lat, lng, base, next_version, version_src["id"])
        await _attach_and_recompute(db, area_id, report_id)
        log.info(
            "report_clustered", area_id=str(area_id), mode="version",
            designation=_designation(base, next_version),
        )
        return area_id

    # 3) Brand-new area.
    base = int(await db.fetchval("select nextval('public.areas_base_number_seq')"))
    area_id = await _create_area(db, lat, lng, base, 1, None)
    await _attach_and_recompute(db, area_id, report_id)
    log.info("report_clustered", area_id=str(
        area_id), mode="new", 
        designation=_designation(base, 1))
    return area_id


async def _create_area(
    db: Database,
    lat: float,
    lng: float,
    base_number: int,
    version: int,
    parent_area_id: UUID | None,
) -> UUID:
    """Insert a new pending area centered on the report's coordinates."""
    new_id: UUID = await db.fetchval(
        """
        insert into public.areas
            (designation, base_number, version, parent_area_id,
             centroid_lat, centroid_lng, status, reported_at)
        values ($1, $2, $3, $4, $5, $6, 'pending', now())
        returning id
        """,
        _designation(base_number, version),
        base_number,
        version,
        parent_area_id,
        lat,
        lng,
    )
    return new_id


async def _attach_and_recompute(db: Database, area_id: UUID, report_id: UUID) -> None:
    """Add the report to the area, then recompute centroid + confidence."""
    await db.execute(
        "insert into public.area_reports (area_id, report_id) values ($1, $2) "
        "on conflict do nothing",
        area_id,
        report_id,
    )
    await recompute_area(db, area_id)


async def recompute_area(db: Database, area_id: UUID) -> None:
    """Recompute centroid + confidence (0.4*N + 0.3*S + 0.3*V) and detect overlaps."""
    rows = await db.fetch(
        """
        select r.device_lat as lat, r.device_lng as lng, r.user_verified_percent as vp
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        where ar.area_id = $1
        """,
        area_id,
    )
    n = len(rows)
    if n == 0:
        return
    lats = [float(r["lat"]) for r in rows]
    lngs = [float(r["lng"]) for r in rows]
    c_lat = sum(lats) / n
    c_lng = sum(lngs) / n
    distances = [haversine_m(c_lat, c_lng, la, lo) for la, lo in zip(lats, lngs, strict=True)]
    sigma = statistics.pstdev(distances) if n > 1 else 0.0

    n_score = min(n / 10.0, 1.0)
    s_score = max(0.0, 1.0 - sigma / float(_CLUSTER_RADIUS_M))
    v_score = (sum(float(r["vp"]) for r in rows) / n) / 100.0
    confidence = 0.4 * n_score + 0.3 * s_score + 0.3 * v_score

    await db.execute(
        """
        update public.areas
           set centroid_lat = $2, centroid_lng = $3, report_count = $4,
               n_score = $5, s_score = $6, v_score = $7, confidence_score = $8
         where id = $1
        """,
        area_id,
        c_lat,
        c_lng,
        n,
        round(n_score, 4),
        round(s_score, 4),
        round(v_score, 4),
        round(confidence, 4),
    )
    await _detect_overlaps(db, area_id)


_OVERLAP_RADIUS_M = 600
_OVERLAP_WINDOW = "120 seconds"


async def _detect_overlaps(db: Database, area_id: UUID) -> None:
    """Record pending overlaps with other active areas whose centroids are <600 m apart."""
    others = await db.fetch(
        f"""
        select b.id as other_id, extensions.ST_Distance(a.centroid, b.centroid) as dist
        from public.areas a
        join public.areas b on b.id <> a.id
        where a.id = $1
          and a.status not in ('resolved', 'rejected')
          and b.status not in ('resolved', 'rejected')
          and extensions.ST_DWithin(a.centroid, b.centroid, {_OVERLAP_RADIUS_M})
        """,
        area_id,
    )
    for row in others:
        other_id: UUID = row["other_id"]
        distance = float(row["dist"])
        a_id, b_id = (area_id, other_id) if area_id < other_id else (other_id, area_id)
        await db.execute(
            f"""
            insert into public.area_overlaps (area_a_id, area_b_id, distance_m, expires_at)
            values ($1, $2, $3, now() + interval '{_OVERLAP_WINDOW}')
            on conflict (area_a_id, area_b_id) do nothing
            """,
            a_id,
            b_id,
            distance,
        )