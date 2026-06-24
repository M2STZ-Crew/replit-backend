"""Notification response schemas (Phase 8, Section 3.5)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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