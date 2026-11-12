"""Who owes a Post-Incident Report, and when the CIAR may be written (12 Nov 2026).

"Only organizations that joined an incident can file a PIR"; "one
organization's PIR clears it for other joined organizations" (it must not);
"CIAR must not initialize until every joined organization has filed its PIR
(queue)".

A team *joined* an incident when it acknowledged it (``area_acceptances``)
or someone of it went (``dispatch_logs``, not withdrawn), and it is a fire
team — Fire Volunteers or BFP, whose captains file (PRD v14 §4.5.4; police,
medical and barangay take part without a truck or crew to record). A team is
its organisation, or a captain who has none.

Every joined team files its own report. The incident stays at "To file" (status
``post_incident_report``) until the last of them has, and that filing closes
it; only then is the CIAR written. An incident no fire team joined (an Admin
pressed fire out on a report nobody went to) is filed by any captain who can
see it, and the first report closes it, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.services.incident import COORDINATING_AGENCIES

_FIRE = ", ".join(f"'{a}'" for a in COORDINATING_AGENCIES)


def expected_teams_sql(area: str) -> str:
    """SQL rows (``team``): the fire teams that joined the Area ``area`` (an SQL
    expression), one row each, never null."""
    return f"""
        select x.organization_id as team
          from public.area_acceptances x
         where x.area_id = {area}
           and x.organization_id is not null
           and x.agency::text in ({_FIRE})
        union
        select coalesce(d.organization_id,
                        case when u.role::text = 'sub_admin' then d.responder_id end) as team
          from public.dispatch_logs d
          join public.users u on u.id = d.responder_id
         where d.area_id = {area}
           and d.status <> 'withdrawn'
           and u.agency_type::text in ({_FIRE})
           and coalesce(d.organization_id,
                        case when u.role::text = 'sub_admin' then d.responder_id end)
               is not null
    """


def waiting_count_sql(area: str) -> str:
    """SQL scalar: how many joined fire teams have not filed for ``area``."""
    return f"""
        (select count(*) from ({expected_teams_sql(area)}) e
          where not exists (
            select 1 from public.post_incident_reports pr
             where pr.area_id = {area}
               and coalesce(pr.organization_id, pr.filed_by) = e.team))
    """


@dataclass(frozen=True)
class PirProgress:
    """Who was expected to file for an incident, and who has."""

    expected: frozenset[UUID]
    filed: frozenset[UUID]
    waiting_names: tuple[str, ...] = ()

    @property
    def waiting(self) -> frozenset[UUID]:
        return self.expected - self.filed

    @property
    def complete(self) -> bool:
        """Every joined team has filed (and at least one report exists): the
        incident closes, and its CIAR may be written."""
        return bool(self.filed) and not self.waiting

    def may_file(self, team: UUID) -> bool:
        """Whether ``team`` may file: it joined — or no fire team did."""
        return not self.expected or team in self.expected


async def pir_progress(db: Any, area_id: UUID) -> PirProgress:
    """Read who joined, who filed, and the names of those still to file.
    ``db`` is the pool or a connection inside the caller's transaction."""
    row = await db.fetchrow(
        f"""
        with expected as ({expected_teams_sql("$1")}),
             filed as (
               select distinct coalesce(p.organization_id, p.filed_by) as team
                 from public.post_incident_reports p
                where p.area_id = $1)
        select
          coalesce((select array_agg(team) from expected), '{{}}') as expected,
          coalesce((select array_agg(team) from filed), '{{}}') as filed,
          coalesce((select array_agg(coalesce(o.name, u.full_name, 'A team')
                                     order by coalesce(o.name, u.full_name))
                      from expected e
                      left join public.organizations o on o.id = e.team
                      left join public.users u on u.id = e.team
                     where e.team not in (select team from filed)), '{{}}')
            as waiting_names
        """,
        area_id,
    )
    if row is None:
        return PirProgress(frozenset(), frozenset())
    return PirProgress(
        expected=frozenset(row.get("expected") or ()),
        filed=frozenset(row.get("filed") or ()),
        waiting_names=tuple(row.get("waiting_names") or ()),
    )
