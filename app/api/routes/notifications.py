"""Neighborhood notification response endpoint (Phase 8, Section 3.5).

Lets a user record their Report/Ignore reply to a 300 m crowdsourced alert.
Recording any response stops further alerts for that (area, user): the worker in
``app.workers.neighborhood`` excludes recipients whose ``response`` is set.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.notification import NotificationRespondRequest

log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post(
    "/respond",
    response_model=MessageResponse,
    summary="Respond to a neighborhood alert (Report/Ignore)",
)
async def respond_to_alert(
    payload: NotificationRespondRequest, user: CurrentUser, db: DatabaseDep
) -> MessageResponse:
    """Record the caller's Report/Ignore response; stops further alerts for this area.

    Upserts ``neighborhood_notifications`` on the ``(area_id, user_id)`` unique key,
    so a response is accepted whether or not the user was ever alerted (e.g. a user
    who self-reports before a tick reaches them is still opted out of future pushes).
    """
    exists = await db.fetchval(
        "select 1 from public.areas where id = $1",
        payload.area_id,
    )
    if not exists:
        raise NotFoundError("Area not found.")

    await db.execute(
        """
        insert into public.neighborhood_notifications
            (area_id, user_id, response, responded_at)
        values ($1, $2, $3::public.neighborhood_response, now())
        on conflict (area_id, user_id) do update
           set response = $3::public.neighborhood_response,
               responded_at = now()
        """,
        payload.area_id,
        user.id,
        payload.response,
    )
    log.info(
        "neighborhood_response_recorded",
        user_id=str(user.id),
        area_id=str(payload.area_id),
        response=payload.response,
    )
    return MessageResponse(message=f"Response '{payload.response}' recorded.")