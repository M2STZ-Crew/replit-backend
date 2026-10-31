"""Notification response schemas (Phase 8, Section 3.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    """One in-app inbox notification for the caller."""

    id: UUID
    type: str
    title: str
    body: str
    data: dict[str, Any] = Field(default_factory=dict)
    is_read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    """Unread-notification count for the bell badge."""

    count: int = 0


class NotificationRespondRequest(BaseModel):
    """Caller's response to a 150 m crowdsourced neighborhood alert.

    ``report`` confirms a fire nearby; ``ignore`` dismisses it; ``safe`` says the
    caller is safe, which only ever comes from them saying so: being alerted
    implies nothing. Any of them, once recorded, stops further alerts for this
    (area, user) — the neighborhood worker skips any recipient whose ``response``
    is set.
    """

    area_id: UUID = Field(description="Area the neighborhood alert referred to.")
    response: Literal["report", "ignore", "safe"] = Field(
        description=(
            "'report' to confirm a fire nearby; 'ignore' to dismiss future alerts; "
            "'safe' to say you are safe (residents the alert reached, while it is live)."
        ),
    )


class AlertAnswer(BaseModel):
    """Where the caller stands with one neighborhood alert, for the alert screen."""

    response: str | None = None
    responded_at: datetime | None = None
    can_say_safe: bool = Field(
        default=False,
        description="The alert reached them, the Area is live, and they have not said so yet.",
    )