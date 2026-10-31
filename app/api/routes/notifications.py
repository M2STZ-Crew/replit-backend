"""Neighborhood notification response endpoint (Phase 8, Section 3.5).

Lets a user record their Report/Ignore reply to a 150 m crowdsourced alert, or
say they are safe (PRD v14 §4.2, §4.11). Recording any response stops further
alerts for that (area, user): the worker in ``app.workers.neighborhood`` excludes
recipients whose ``response`` is set.

"I am safe" is for a resident the alert reached, while the Area is live, and
only ever from them saying so. It stands once given: a later Report or Ignore
does not take it back, and giving it twice changes nothing.
"""

from __future__ import annotations

import json
from uuid import UUID

from asyncpg import Record
from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.common import MessageResponse
from app.schemas.notification import (
    AlertAnswer,
    NotificationItem,
    NotificationRespondRequest,
    UnreadCount,
)
from app.services.incident import OFF_FEED_STATUSES

log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _alert_state(db: Database, area_id: UUID, user_id: UUID) -> Record:
    """The Area's status and this user's row for its alert; 404 for no such Area."""
    row = await db.fetchrow(
        """
        select a.status::text as status,
               coalesce(n.alerts_sent, 0) as alerts_sent,
               n.response::text as response,
               n.responded_at
        from public.areas a
        left join public.neighborhood_notifications n
               on n.area_id = a.id and n.user_id = $2
        where a.id = $1
        """,
        area_id,
        user_id,
    )
    if row is None:
        raise NotFoundError("Area not found.")
    return row


@router.get("", response_model=list[NotificationItem], summary="List my notifications")
async def list_notifications(
    user: CurrentUser, db: DatabaseDep, limit: int = 100
) -> list[NotificationItem]:
    """The caller's in-app notification inbox, newest first."""
    rows = await db.fetch(
        """
        select id, type, title, body, data, is_read, created_at
        from public.notifications
        where user_id = $1
        order by created_at desc
        limit $2
        """,
        user.id,
        min(max(limit, 1), 200),
    )
    items: list[NotificationItem] = []
    for r in rows:
        data = dict(r)
        raw = data.get("data")
        data["data"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        items.append(NotificationItem.model_validate(data))
    return items


@router.get(
    "/unread-count", response_model=UnreadCount, summary="My unread notification count"
)
async def unread_count(user: CurrentUser, db: DatabaseDep) -> UnreadCount:
    """Count of the caller's unread notifications (for the bell badge)."""
    n = await db.fetchval(
        "select count(*) from public.notifications where user_id = $1 and is_read = false",
        user.id,
    )
    return UnreadCount(count=int(n or 0))


@router.post("/read-all", response_model=MessageResponse, summary="Mark all read")
async def mark_all_read(user: CurrentUser, db: DatabaseDep) -> MessageResponse:
    """Mark all of the caller's notifications as read."""
    await db.execute(
        "update public.notifications set is_read = true "
        "where user_id = $1 and is_read = false",
        user.id,
    )
    return MessageResponse(message="All notifications marked read.")


@router.post(
    "/{notification_id}/read", response_model=MessageResponse, summary="Mark one read"
)
async def mark_read(
    notification_id: UUID, user: CurrentUser, db: DatabaseDep
) -> MessageResponse:
    """Mark a single notification (the caller's own) as read."""
    await db.execute(
        "update public.notifications set is_read = true where id = $1 and user_id = $2",
        notification_id,
        user.id,
    )
    return MessageResponse(message="Notification marked read.")


@router.get(
    "/respond/{area_id}",
    response_model=AlertAnswer,
    summary="My answer to a neighborhood alert",
)
async def my_alert_answer(
    area_id: UUID, user: CurrentUser, db: DatabaseDep
) -> AlertAnswer:
    """What the caller answered, and whether they may still say they are safe."""
    state = await _alert_state(db, area_id, user.id)
    return AlertAnswer(
        response=state["response"],
        responded_at=state["responded_at"],
        can_say_safe=(
            state["alerts_sent"] > 0
            and state["status"] not in OFF_FEED_STATUSES
            and state["response"] != "safe"
        ),
    )


@router.post(
    "/respond",
    response_model=MessageResponse,
    summary="Respond to a neighborhood alert (Report/Ignore/Safe)",
)
async def respond_to_alert(
    payload: NotificationRespondRequest, user: CurrentUser, db: DatabaseDep
) -> MessageResponse:
    """Record the caller's response; stops further alerts for this area.

    Upserts ``neighborhood_notifications`` on the ``(area_id, user_id)`` unique key,
    so Report and Ignore are accepted whether or not the user was ever alerted (e.g.
    a user who self-reports before a tick reaches them is still opted out of future
    pushes). ``safe`` is not: it answers an alert, so the alert must have reached
    them and the fire must still be live.
    """
    state = await _alert_state(db, payload.area_id, user.id)
    if payload.response == "safe":
        if state["status"] in OFF_FEED_STATUSES:
            raise ConflictError("This fire is over, so there is nothing to answer.")
        if state["alerts_sent"] <= 0:
            raise ForbiddenError("Only residents alerted about this fire can answer it.")

    # response::text: comparing to the literal would fail on a database that has
    # not had migration 20261031090100, and Report and Ignore must keep working.
    await db.execute(
        """
        insert into public.neighborhood_notifications
            (area_id, user_id, response, responded_at)
        values ($1, $2, $3::public.neighborhood_response, now())
        on conflict (area_id, user_id) do update
           set response = case
                   when public.neighborhood_notifications.response::text = 'safe'
                   then public.neighborhood_notifications.response
                   else excluded.response end,
               responded_at = case
                   when public.neighborhood_notifications.response::text = 'safe'
                   then public.neighborhood_notifications.responded_at
                   else excluded.responded_at end
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