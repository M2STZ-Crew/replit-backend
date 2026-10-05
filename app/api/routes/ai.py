"""Post-incident AI summary endpoints (Phase 11, Section 3.6).

Generate a DeepSeek 'fire-out' report for a resolved incident and list prior
summaries. Generation is restricted to sub-admins/admin with agency visibility; the
incident must be resolved.

v1.12.5 adds the coordinators' AI summaries list (``GET /ai-summaries``): every
incident a team has filed a report for, with its newest summary. Summaries are
written automatically when a report is filed; the list writes any that are
missing — incidents from before the AI key was set, or a write that failed — so
nobody has to ask for one.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query

from app.api.deps import DatabaseDep, DeepSeekClientDep, StaffUser
from app.core.config import get_settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.ai import AISummaryResponse, SummarizedIncident
from app.schemas.auth import AuthenticatedUser
from app.services.ai_summary import (
    BACKFILL_PER_LOAD,
    claim_summary,
    generate_incident_summary,
    list_incident_summaries,
    list_summarized_incidents,
    summarize_in_background,
    summary_state,
)
from app.services.incident import assert_coordinator, visible_agencies

log = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["ai"])
# Not under /incidents: GET /incidents/{incident_id} would take the word as an id.
summaries_router = APIRouter(prefix="/ai-summaries", tags=["ai"])


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


@router.post(
    "/{incident_id}/summary",
    response_model=AISummaryResponse,
    summary="Generate a post-incident fire-out summary (DeepSeek)",
)
async def generate_summary(
    incident_id: UUID,
    user: StaffUser,
    db: DatabaseDep,
    client: DeepSeekClientDep,
) -> AISummaryResponse:
    """Generate and store a fire-out report for a resolved incident (coordinator only)."""
    assert_coordinator(user, "generate incident summaries")
    status_val = await db.fetchval(
        "select status::text from public.areas where id = $1", incident_id
    )
    if status_val is None:
        raise NotFoundError("Incident not found.")
    await _assert_visible(db, incident_id, user)
    # Fire out passes through 'fire_out' into the Post-Incident Report step and
    # then 'closed' (v11 Section 2.5); each of them is after the fire.
    if status_val not in ("fire_out", "post_incident_report", "closed"):
        raise ConflictError(
            "A fire-out report can only be generated once the fire is out.",
            details={"current_status": status_val},
        )
    row = await generate_incident_summary(db, client, incident_id)
    log.info("ai_summary_generated", incident_id=str(incident_id), user_id=str(user.id))
    return AISummaryResponse.model_validate(row)


@router.get(
    "/{incident_id}/summaries",
    response_model=list[AISummaryResponse],
    summary="List stored AI summaries for an incident",
)
async def list_summaries(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> list[AISummaryResponse]:
    """List prior fire-out summaries for an incident (visibility-checked)."""
    exists = await db.fetchval("select 1 from public.areas where id = $1", incident_id)
    if exists is None:
        raise NotFoundError("Incident not found.")
    await _assert_visible(db, incident_id, user)
    rows = await list_incident_summaries(db, incident_id)
    return [AISummaryResponse.model_validate(r) for r in rows]


@summaries_router.get(
    "",
    response_model=list[SummarizedIncident],
    summary="The AI summaries list: every incident a team has filed a report for",
)
async def list_summarized(
    user: StaffUser,
    db: DatabaseDep,
    background: BackgroundTasks,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SummarizedIncident]:
    """Coordinators' list, newest first, each with its newest summary.

    An incident whose summary is missing, or older than its newest report, is
    returned as "writing" and its summary is started after the response — at
    most BACKFILL_PER_LOAD per load, and once per incident in ten minutes.
    """
    assert_coordinator(user, "read the AI summaries")
    rows = await list_summarized_incidents(db, visible_agencies(user), limit=limit)
    configured = get_settings().deepseek_configured
    started: list[str] = []
    items: list[SummarizedIncident] = []
    for row in rows:
        state = summary_state(row, configured=configured)
        if (
            state == "writing"
            and len(started) < BACKFILL_PER_LOAD
            and claim_summary(row["area_id"])
        ):
            background.add_task(summarize_in_background, row["area_id"])
            started.append(str(row["area_id"]))
        items.append(
            SummarizedIncident.model_validate(
                {**row, "teams": list(row["teams"] or []), "state": state}
            )
        )
    if started:
        log.info("ai_summary_backfill", incidents=started, user_id=str(user.id))
    return items
