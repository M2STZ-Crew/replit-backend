"""The Admin Dashboard's statistics (v1.12.50).

22 Nov 2026: "Maglagay ng Statistic Panel ( or gawing Statistic Dashboard
nalang yung 'Response measures' )", answered "Statistics dashboard": 7, 30 or
90 days; four measures against the period before; fires per day, top
barangays, alarm levels and fire types; an organization's Admin switches
between its organization and all incidents.

* A day is Manila's, and a period ends now: 7 days is today and the six days
  before it. The period before is the same length of time, 7 days earlier, so
  half of today is never set against a whole day.
* A change is given only when the records cover that earlier period.
  Production was reset on 13 Nov 2026: what came before is unknown, not zero.
* "Your organization" is the fires routed to it, the Incidents card's rule,
  and its time to acknowledge is to its own first acknowledgement. On scene
  is the first team's, whoever's.
* A false alarm is a fire rejected, or closed as one by a team that went: what
  may earn a prank strike (report_strikes.assert_markable). It is no fire in
  the counts and charts. Its response times still count.
* A merged fire is left out: its reports moved to the one that stayed.

Counts and medians only; nothing here names a person.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, get_args

from app.db.session import Database
from app.schemas.alarm import AlarmLevel
from app.schemas.auth import AuthenticatedUser
from app.schemas.statistics import (
    BarangayCount,
    CountStatistic,
    DayCount,
    IncidentStatistics,
    KeyCount,
    MeasureStatistic,
    StatisticsScope,
)
from app.services.access import admin_access
from app.services.incident import requested_sql

# The Philippines keeps one offset all year.
MANILA = timezone(timedelta(hours=8))
PERIODS = (7, 30, 90)
TOP_BARANGAYS = 5

_LADDER: tuple[str, ...] = get_args(AlarmLevel)

_ANY_ACKNOWLEDGED = "a.verified_at"
_OURS_ACKNOWLEDGED = (
    "(select min(x.accepted_at) from public.area_acceptances x "
    "where x.area_id = a.id and x.organization_id = $4)"
)


def _rows_sql(acknowledged: str, scope: str) -> str:
    # A fire named before the barangays were loaded (v1.12.45) has no code
    # stored: where it is says which it was.
    return f"""
        select a.reported_at, a.arrived_at, a.verified_at,
               {acknowledged} as acknowledged_at,
               a.alarm_level::text as alarm_level,
               to_jsonb(a) ->> 'fire_type' as fire_type,
               coalesce(named.pcode, found.pcode) as barangay_pcode,
               coalesce(named.name, found.name) as barangay_name,
               coalesce(named.city, found.city) as barangay_city,
               (a.rejected_at is not null
                or a.status::text in ('rejected', 'declined')
                or exists (select 1 from public.post_incident_reports p
                            where p.area_id = a.id and p.false_alarm)) as false_alarm
          from public.areas a
          left join public.barangays named
                 on named.pcode = to_jsonb(a) ->> 'barangay_pcode'
          left join lateral (
                select b.pcode, b.name, b.city
                  from public.barangays b
                 where named.pcode is null
                   and extensions.ST_Intersects(
                         b.geom,
                         extensions.ST_Transform(
                           extensions.ST_SetSRID(
                             extensions.ST_MakePoint(a.centroid_lng, a.centroid_lat), 4326),
                           32651))
                 order by b.pcode
                 limit 1
          ) found on true
         where a.status::text <> 'merged'
           and a.reported_at >= $1
           and a.reported_at <= $2
           {scope}
    """


def windows(days: int, now: datetime) -> tuple[datetime, datetime, datetime]:
    """The period's start, then the start and the end of the one before it."""
    midnight = now.astimezone(MANILA).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days - 1)
    before = start - timedelta(days=days)
    return start, before, before + (now - start)


def covers(since: datetime | None, period_start: datetime) -> bool:
    """Whether the records reach back over a period, by its first Manila day."""
    if since is None:
        return False
    return since.astimezone(MANILA).date() <= period_start.astimezone(MANILA).date()


def _minutes(rows: Iterable[Mapping[str, Any]], begin: str, end: str) -> list[float]:
    gaps = ((r[end] - r[begin]).total_seconds() / 60 for r in rows if r[begin] and r[end])
    return [gap for gap in gaps if gap >= 0]


def _middle(values: Sequence[float]) -> float | None:
    return round(median(values), 2) if values else None


def _false_share(rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, int]:
    """False alarms out of the reports decided either way."""
    decided = [r for r in rows if r["verified_at"] or r["false_alarm"]]
    if not decided:
        return None, 0
    return round(sum(1 for r in decided if r["false_alarm"]) / len(decided), 4), len(decided)


def summarise(
    rows: Sequence[Mapping[str, Any]],
    *,
    days: int,
    scope: StatisticsScope,
    now: datetime,
    since: datetime | None,
) -> IncidentStatistics:
    """The Dashboard's numbers from both periods' rows."""
    start, before_start, before_end = windows(days, now)
    comparable = covers(since, before_start)
    current = [r for r in rows if start <= r["reported_at"] <= now]
    before = [r for r in rows if before_start <= r["reported_at"] <= before_end]

    def timed(begin: str, end: str) -> MeasureStatistic:
        values = _minutes(current, begin, end)
        previous = _middle(_minutes(before, begin, end)) if comparable else None
        return MeasureStatistic(value=_middle(values), n=len(values), previous=previous)

    fires = [r for r in current if not r["false_alarm"]]
    share, decided = _false_share(current)

    per_day = Counter(r["reported_at"].astimezone(MANILA).date() for r in fires)
    first_day = start.astimezone(MANILA).date()
    by_level = Counter(r["alarm_level"] for r in fires)
    by_type = Counter(r["fire_type"] for r in fires)
    by_barangay = Counter(r["barangay_pcode"] for r in fires if r["barangay_pcode"])
    named = {r["barangay_pcode"]: r for r in fires if r["barangay_pcode"]}
    # The most first; a tie by name, so a refresh never reorders it.
    top = sorted(
        by_barangay,
        key=lambda code: (-by_barangay[code], str(named[code]["barangay_name"]), code),
    )[:TOP_BARANGAYS]
    types = sorted((k for k in by_type if k), key=lambda key: (-by_type[key], key))

    return IncidentStatistics(
        days=days,
        scope=scope,
        start=start,
        end=now,
        records_since=since,
        comparable=comparable,
        minutes_to_acknowledge=timed("reported_at", "acknowledged_at"),
        # From the first acknowledgement to the first team there, in either scope.
        minutes_to_scene=timed("verified_at", "arrived_at"),
        fires=CountStatistic(
            value=len(fires),
            previous=sum(1 for r in before if not r["false_alarm"]) if comparable else None,
        ),
        false_alarms=MeasureStatistic(
            value=share, n=decided, previous=_false_share(before)[0] if comparable else None
        ),
        per_day=[
            DayCount(day=day, count=per_day[day])
            for day in (first_day + timedelta(days=i) for i in range(days))
        ],
        barangays=[
            BarangayCount(
                pcode=code,
                name=named[code]["barangay_name"],
                city=named[code]["barangay_city"],
                count=by_barangay[code],
            )
            for code in top
        ],
        without_barangay=sum(1 for r in fires if not r["barangay_pcode"]),
        # The ladder's order, and those with no alarm last.
        alarm_levels=[
            *(KeyCount(key=level, count=by_level[level]) for level in _LADDER),
            KeyCount(key=None, count=by_level[None]),
        ],
        fire_types=[
            *(KeyCount(key=key, count=by_type[key]) for key in types),
            *([KeyCount(key=None, count=by_type[None])] if by_type[None] else []),
        ],
    )


async def incident_statistics(
    db: Database,
    admin: AuthenticatedUser,
    days: int,
    scope: StatisticsScope | None = None,
    *,
    now: datetime | None = None,
) -> IncidentStatistics:
    """``scope`` is "org" unless told otherwise, for an Admin with one of its own.

    The central hub and the system Admin act on every incident, so theirs is
    always "all", and the answer says so.
    """
    now = now or datetime.now(MANILA)
    access = admin_access(admin)
    own_only = (
        scope != "all"
        and access is not None
        and access.act_agencies is not None
        and access.organization_id is not None
    )
    _, before_start, _ = windows(days, now)
    params: list[Any] = [before_start, now]
    acknowledged, narrowed = _ANY_ACKNOWLEDGED, ""
    if own_only:
        assert access is not None and access.act_agencies is not None
        params += [list(access.act_agencies), access.organization_id]
        acknowledged = _OURS_ACKNOWLEDGED
        narrowed = f"and {requested_sql('a.id', 3)}"
    rows = await db.fetch(_rows_sql(acknowledged, narrowed), *params)
    since = await db.fetchval(
        "select min(reported_at) from public.areas where status::text <> 'merged'"
    )
    return summarise(
        [dict(row) for row in rows],
        days=days,
        scope="org" if own_only else "all",
        now=now,
        since=since,
    )
