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
    """Caller's response to a 300 m crowdsourced neighborhood alert.

    ``report`` confirms a fire nearby; ``ignore`` dismisses it. Either value, once
    recorded, stops further alerts for this (area, user) — the neighborhood worker
    skips any recipient whose ``response`` is set.
    """

    area_id: UUID = Field(description="Area the neighborhood alert referred to.")
    response: Literal["report", "ignore"] = Field(
        description="'report' to confirm a fire nearby; 'ignore' to dismiss future alerts.",
    )