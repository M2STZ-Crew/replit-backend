"""Incident PDF report endpoint (Phase 14).

Streams a one-page fire-out PDF for an incident (visibility-checked staff). Reuses
the structured facts from app.services.ai_summary and the latest stored AI summary.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import DatabaseDep, StaffUser
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.services.ai_summary import gather_incident_facts
from app.services.incident import visible_agencies
from app.services.pdf_report import build_fire_out_pdf

log = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def _assert_visible(db: Database, area_id: UUID, user: AuthenticatedUser) -> None:
    """Raise 403 unless the incident is visible to the caller's agency (admin: always)."""
    agencies = visible_agencies(user)
    if agencies is None:
        return
    if not agencies:
        raise ForbiddenError("This incident is not visible to your agency.")
    visible = await db.fetchval(
        """
        select exists (
            select 1 from public.area_reports ar
            join public.reports r on r.id = ar.report_id
            where ar.area_id = $1
              and r.selected_agencies && $2::public.agency_type[]
        )
        """,
        area_id,
        agencies,
    )
    if not visible:
        raise ForbiddenError("This incident is not visible to your agency.")


@router.get(
    "/{incident_id}/report.pdf",
    summary="Download the incident report (PDF)",
    response_class=Response,
)
async def incident_report_pdf(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> Response:
    """Generate and stream the incident fire-out report as a PDF."""
    exists = await db.fetchval("select 1 from public.areas where id = $1", incident_id)
    if exists is None:
        raise NotFoundError("Incident not found.")
    await _assert_visible(db, incident_id, user)

    facts = await gather_incident_facts(db, incident_id)
    summary_text: str | None = await db.fetchval(
        """
        select summary_text from public.ai_summaries
        where area_id = $1 order by generated_at desc limit 1
        """,
        incident_id,
    )
    pdf_bytes = build_fire_out_pdf(facts.structured, summary_text)
    log.info("incident_pdf_generated", incident_id=str(incident_id), by=str(user.id))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}.pdf"'
        },
    )