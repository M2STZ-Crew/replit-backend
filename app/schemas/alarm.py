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

# Where a request stands (the request_status enum).
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]

# Each level in the words BFP uses, for pushes and messages.
_LABELS: dict[str, str] = {
    "positive_fire_alarm": "Positive fire alarm",
    "first_alarm": "1st alarm",
    "second_alarm": "2nd alarm",
    "third_alarm": "3rd alarm",
    "fourth_alarm": "4th alarm",
    "fifth_alarm": "5th alarm",
    "general_alarm": "General alarm",
}


def alarm_label(level: str | None) -> str:
    """"2nd alarm", as BFP says it; "no alarm level" before one is set."""
    return _LABELS.get(level or "", "no alarm level")


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
    # The Area as it stands: how far along, its alarm level now, and where it
    # is — so BFP sees what it is deciding on, and the queue can open it.
    area_status: str | None = None
    area_alarm_level: str | None = None
    area_centroid_lat: float | None = None
    area_centroid_lng: float | None = None
    requested_by: UUID
    requested_by_name: str | None = None
    # The asker's organisation: its Admin may cancel or delete the request.
    requested_by_organization_id: UUID | None = None
    requested_by_organization_name: str | None = None
    requested_alarm_level: str
    justification: str | None = None
    status: str
    reviewed_by: UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    executed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime