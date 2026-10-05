"""Incident PDF report endpoint (Phase 14).

Streams the incident report PDF (visibility-checked staff): the incident, its
timeline, every responding team's Post-Incident Report, and the latest AI
summary. Reuses the structured facts from app.services.ai_summary.

The PDF is built at each download, never stored, so it always carries every
report filed so far and the newest summary.

v1.12.5: the app downloads it in the phone's browser, which cannot send the
sign-in token. The app asks for a five-minute link first (``report-link``) and
the browser opens that (``report-download``); see app.services.report_links.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import DatabaseDep, StaffUser
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.ai import ReportLinkResponse
from app.schemas.auth import AuthenticatedUser
from app.services.ai_summary import PH_TIME, gather_incident_facts
from app.services.incident import visible_agencies
from app.services.pdf_report import build_fire_out_pdf
from app.services.report_links import (
    ExpiredReportLinkError,
    InvalidReportLinkError,
    sign_report_link,
    verify_report_link,
)

_STAFF_ROLES = ("admin", "sub_admin", "response_team")

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
    pdf_bytes, _ = await _build_pdf(db, incident_id)
    log.info("incident_pdf_generated", incident_id=str(incident_id), by=str(user.id))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}.pdf"'
        },
    )


async def _build_pdf(db: Database, incident_id: UUID) -> tuple[bytes, str]:
    """The PDF, and a file name a person can find in Downloads."""
    facts = await gather_incident_facts(db, incident_id)
    # The newest summary: it is rewritten each time another team files, so the
    # latest is the one that covers every report in the facts.
    summary = await db.fetchrow(
        """
        select summary_text, model from public.ai_summaries
        where area_id = $1 order by generated_at desc limit 1
        """,
        incident_id,
    )
    pdf_bytes = build_fire_out_pdf(
        facts.structured,
        summary["summary_text"] if summary else None,
        summary_model=summary["model"] if summary else None,
    )
    return pdf_bytes, _file_name(facts.structured)


def _file_name(structured: dict[str, object]) -> str:
    """The incident and its day in Philippine time: Fire-report-Area-3-2026-10-05.pdf."""
    designation = re.sub(r"[^A-Za-z0-9]+", "-", str(structured.get("designation") or ""))
    name = "Fire-report-" + (designation.strip("-") or "incident")
    timestamps = structured.get("timestamps")
    reported = timestamps.get("reported_at") if isinstance(timestamps, dict) else None
    if isinstance(reported, str):
        try:
            name += f"-{datetime.fromisoformat(reported).astimezone(PH_TIME):%Y-%m-%d}"
        except ValueError:
            pass
    return name + ".pdf"


@router.post(
    "/{incident_id}/report-link",
    response_model=ReportLinkResponse,
    summary="A five-minute link to download the incident report in a browser",
)
async def incident_report_link(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> ReportLinkResponse:
    """Who may download the PDF may have a link to it: visibility-checked staff.

    The link is made for this user and this incident; the download checks again.
    """
    exists = await db.fetchval("select 1 from public.areas where id = $1", incident_id)
    if exists is None:
        raise NotFoundError("Incident not found.")
    await _assert_visible(db, incident_id, user)
    token, expires_at = sign_report_link(incident_id, user.id)
    return ReportLinkResponse(
        path=f"/incidents/{incident_id}/report-download?token={token}",
        expires_at=expires_at,
    )


def _browser_message(status_code: int, text: str) -> Response:
    """A browser opened this, not the app: say what happened in words, not JSON."""
    return Response(
        content=text,
        status_code=status_code,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


_TRY_AGAIN = "Go back to RepLiT and tap Download PDF again."


@router.get(
    "/{incident_id}/report-download",
    summary="Download the incident report with a link from report-link (no sign-in header)",
    response_class=Response,
)
async def incident_report_download(
    incident_id: UUID,
    db: DatabaseDep,
    token: Annotated[str, Query(max_length=200)],
) -> Response:
    """Stream the PDF to a browser that holds a valid link.

    The person the link was made for must still be active staff who can see
    the incident — a link made before they were deactivated, or moved to
    another agency, stops working at once rather than in five minutes.
    """
    try:
        user_id = verify_report_link(incident_id, token)
    except ExpiredReportLinkError:
        return _browser_message(410, f"This download link has expired. {_TRY_AGAIN}")
    except InvalidReportLinkError:
        return _browser_message(403, f"This download link is not valid. {_TRY_AGAIN}")

    row = await db.fetchrow(
        "select id, role::text as role, agency_type::text as agency_type, is_active "
        "from public.users where id = $1",
        user_id,
    )
    if row is None or row["is_active"] is False or row["role"] not in _STAFF_ROLES:
        return _browser_message(403, "This account can no longer download reports.")
    user = AuthenticatedUser(id=row["id"], role=row["role"], agency_type=row["agency_type"])
    if await db.fetchval("select 1 from public.areas where id = $1", incident_id) is None:
        return _browser_message(404, "This incident no longer exists.")
    try:
        await _assert_visible(db, incident_id, user)
    except ForbiddenError:
        return _browser_message(403, "This incident is not visible to your agency.")

    pdf_bytes, file_name = await _build_pdf(db, incident_id)
    log.info("incident_pdf_downloaded", incident_id=str(incident_id), by=str(user_id))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Cache-Control": "private, no-store",
        },
    )