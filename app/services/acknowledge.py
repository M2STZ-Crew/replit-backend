"""Acknowledging an incident, from Accept or from a staff member's own report.

Acknowledging is v12's "verify": the first one moves an Area reported ->
verified and sends nobody; a later one by a captain records that their agency
sees it too. Two ways in:

- POST /incidents/{id}/accept (``app/api/routes/incidents.py``);
- since v1.12.44, a coordinator's or responder's own report (19 Nov 2026,
  "Acknowledged on sending"): they are at the fire, so their report starts
  acknowledged by their organisation, with no self-acknowledge step after it.

The 19 Nov "unexpected error" when a coordinator acknowledged their own report
was the database, not the self-report: the central hub (Barangay 76, all in
one) has Fire Volunteer and medical members, and
``enforce_area_acceptance_org_agency`` refused an acknowledgement whose
organisation is not of the agency, so the hub's members could acknowledge no
fire at all. Migration 20261120120000 lets the hub count for every agency;
until it is applied, and for any other mismatch, the acknowledgement is kept
without its organisation rather than failing with a 500.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import Request

from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.services.access import acting_agency
from app.services.audit import record_audit
from app.services.incident import OFF_FEED_STATUSES, requested_sql, visible_agencies

log = get_logger(__name__)

_INSERT = """
    insert into public.area_acceptances
        (area_id, user_id, agency, organization_id, is_first)
    values ($1, $2, $3::public.agency_type, $4, $5)
"""

#: Who reports a fire as staff, and so acknowledges it by reporting.
OWN_REPORT_ROLES = frozenset({"sub_admin", "response_team"})


async def insert_acceptance(
    conn: asyncpg.Connection,
    incident_id: UUID,
    user: AuthenticatedUser,
    agency: str | None,
    *,
    is_first: bool,
) -> None:
    """Record ``user``'s acknowledgement under ``agency`` and their organisation.

    Inside the caller's transaction. An organisation the database refuses for
    the agency (the central hub before migration 20261120120000) is left off
    the row, in a savepoint, so the acknowledgement itself still stands.
    """
    organization = user.primary_org_id if agency else None
    if organization is not None:
        try:
            async with conn.transaction():
                await conn.execute(
                    _INSERT, incident_id, user.id, agency, organization, is_first
                )
            return
        except asyncpg.CheckViolationError as exc:
            log.warning(
                "acceptance_kept_without_organization",
                incident_id=str(incident_id),
                user_id=str(user.id),
                agency=agency,
                error=str(exc),
            )
    await conn.execute(_INSERT, incident_id, user.id, agency, None, is_first)


@dataclass(frozen=True)
class OwnReportAck:
    """What a staff member's report did to its incident."""

    #: "verified": it moved the incident reported -> verified; "joined": it was
    #: verified already and their agency's acknowledgement was added.
    outcome: Literal["verified", "joined"]
    before: str


async def acknowledge_own_report(
    db: Database,
    request: Request | None,
    user: AuthenticatedUser,
    incident_id: UUID,
) -> OwnReportAck | None:
    """Acknowledge the incident a coordinator's or responder's report joined.

    The rules are Accept's: only an incident their agency may see, never one
    that is no longer live, once per person; a responder adds nothing to an
    incident already verified (their next act is responding). Returns None
    when nothing was recorded.
    """
    if user.role not in OWN_REPORT_ROLES:
        return None
    agency = acting_agency(user)
    agencies = visible_agencies(user)
    if agency is None or not agencies:
        return None
    if not await db.fetchval(f"select {requested_sql('$1', 2)}", incident_id, agencies):
        return None
    async with db.acquire() as conn, conn.transaction():
        current = await conn.fetchval(
            "select status::text from public.areas where id = $1 for update", incident_id
        )
        if current is None or current in OFF_FEED_STATUSES:
            return None
        if await conn.fetchval(
            "select exists (select 1 from public.area_acceptances "
            "where area_id = $1 and user_id = $2)",
            incident_id,
            user.id,
        ):
            return None
        first = current == "reported" and not await conn.fetchval(
            "select exists (select 1 from public.area_acceptances "
            "where area_id = $1 and is_first)",
            incident_id,
        )
        if not first and user.role == "response_team":
            return None
        if first:
            await conn.execute(
                "update public.areas set status = 'verified', verified_by = $2 where id = $1",
                incident_id,
                user.id,
            )
        await insert_acceptance(conn, incident_id, user, agency, is_first=first)
        metadata = {"agency": agency, "role": user.role, "own_report": True}
        if first:
            await record_audit(
                conn,
                request,
                user,
                action="incident.verify",
                entity_type="area",
                entity_id=incident_id,
                area_id=incident_id,
                before_state={"status": current},
                after_state={"status": "verified"},
                metadata=metadata,
            )
        else:
            await record_audit(
                conn,
                request,
                user,
                action="incident.accept.participate",
                entity_type="area",
                entity_id=incident_id,
                area_id=incident_id,
                metadata={**metadata, "first_accept": False, "status_at_accept": current},
            )
    log.info(
        "incident_acknowledged_by_own_report",
        incident_id=str(incident_id),
        user_id=str(user.id),
        agency=agency,
        moved_status=first,
    )
    return OwnReportAck(outcome="verified" if first else "joined", before=current)
