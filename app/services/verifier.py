"""Who verified an incident, and for which organization.

The first Verify writes two things (Master Context v12 §2.5.1):
``areas.verified_by``, and an ``area_acceptances`` row marked ``is_first`` that
carries the verifier's agency and team *as they were at that moment*. The
organization is read from that row, so a volunteer who later moves brigade does
not rewrite who verified last week's fire. An incident verified before v11 has
no such row; for those the verifier's current team is the best record there is.

Staff see the person and the organization (``IncidentDetail``). A citizen sees
the organization only (``TrackingSnapshot``, the "Report verified" push) — the
rule Track It Live already keeps for units: a brigade, never the person holding
the phone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.db.session import Database

# What a citizen is told verified their report when the verifier belongs to no
# team: the agency itself. Admin accounts carry no agency at all.
_AGENCY_NAMES = {
    "fire_volunteer": "the Fire Volunteers",
    "bfp": "the Bureau of Fire Protection",
    "police": "the Police",
    "medical": "the medical team",
    "barangay": "the Barangay",
}
_ADMIN_NAME = "RepLiT Admin"

VERIFIER_SQL = """
select vu.full_name as name, vu.role::text as role, a.verified_at,
       case when f.id is not null then f.agency::text
            else vu.agency_type::text end as agency,
       case when f.id is not null then fo.name else uo.name end as organization
from public.areas a
join public.users vu on vu.id = a.verified_by
left join public.area_acceptances f
       on f.area_id = a.id and f.is_first and f.user_id = a.verified_by
left join public.organizations fo on fo.id = f.organization_id
left join public.organizations uo on uo.id = vu.primary_org_id
where a.id = $1
"""


@dataclass(frozen=True)
class Verifier:
    """The person who verified an incident, and the team they verified it for."""

    name: str | None
    role: str
    agency: str | None
    organization: str | None
    verified_at: datetime | None

    @property
    def public_label(self) -> str:
        """Who a citizen is told verified their report: the team, never the person."""
        if self.organization:
            return self.organization
        if self.agency:
            return _AGENCY_NAMES.get(self.agency, self.agency.replace("_", " ").title())
        return _ADMIN_NAME


async def fetch_verifier(db: Database, area_id: UUID) -> Verifier | None:
    """Who verified ``area_id``; None while it is unverified (or the account is gone)."""
    row = await db.fetchrow(VERIFIER_SQL, area_id)
    if row is None:
        return None
    return Verifier(
        name=row["name"],
        role=row["role"],
        agency=row["agency"],
        organization=row["organization"],
        verified_at=row["verified_at"],
    )
