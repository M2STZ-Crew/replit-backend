"""Post-incident AI summary endpoints (Phase 11, Section 3.6).

Generate a Claude Haiku 'fire-out' report for a resolved incident and list prior
summaries. Generation is restricted to sub-admins/admin with agency visibility; the
incident must be resolved.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AnthropicClientDep, DatabaseDep, StaffUser
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.ai import AISummaryResponse
from app.schemas.auth import AuthenticatedUser
from app.services.ai_summary import generate_incident_summary, list_incident_summaries
from app.services.incident import assert_coordinator, visible_agencies

log = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["ai"])


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
    summary="Generate a post-incident fire-out summary (Claude Haiku)",
)
async def generate_summary(
    incident_id: UUID,
    user: StaffUser,
    db: DatabaseDep,
    client: AnthropicClientDep,
) -> AISummaryResponse:
    """Generate and store a fire-out report for a resolved incident (coordinator only)."""
    assert_coordinator(user, "generate incident summaries")
    status_val = await db.fetchval(
        "select status::text from public.areas where id = $1", incident_id
    )
    if status_val is None:
        raise NotFoundError("Incident not found.")
    await _assert_visible(db, incident_id, user)
    if status_val != "resolved":
        raise ConflictError(
            "A fire-out report can only be generated for a resolved incident.",
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