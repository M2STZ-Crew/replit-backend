"""Alarm-raise request schemas (Phase 13, Section 6, Section 7 #16)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AlarmLevel = Literal[
    "positive_fire_alarm",
    "first_alarm",
    "second_alarm",
    "third_alarm",
    "fourth_alarm",
    "fifth_alarm",
    "general_alarm",
]


class AlarmRequestCreate(BaseModel):
    """Request to raise the alarm level on an incident (Fire-Vol -> BFP)."""

    area_id: UUID
    requested_alarm_level: AlarmLevel
    justification: str | None = Field(default=None, max_length=2000)


class AlarmReviewRequest(BaseModel):
    """Optional reviewer notes on execute/reject."""

    notes: str | None = Field(default=None, max_length=1000)


class AlarmRequestResponse(BaseModel):
    """An alarm-raise request row."""

    id: UUID
    area_id: UUID
    area_designation: str | None = None
    requested_by: UUID
    requested_by_name: str | None = None
    requested_alarm_level: str
    justification: str | None = None
    status: str
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime