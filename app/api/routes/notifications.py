"""Neighborhood notification response endpoint (Phase 8, Section 3.5).

Lets a user record their Report/Ignore reply to a 300 m crowdsourced alert.
Recording any response stops further alerts for that (area, user): the worker in
``app.workers.neighborhood`` excludes recipients whose ``response`` is set.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.notification import (
    NotificationItem,
    NotificationRespondRequest,
    UnreadCount,
)

log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


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