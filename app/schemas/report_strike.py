"""Prank-report strikes: what the resident and the console see (v1.12.41)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AppealState = Literal["none", "pending", "upheld", "overturned"]
StrikeStatus = Literal["awaiting_confirmation", "active", "overturned"]


class StrikeView(BaseModel):
    """One strike, as its resident sees it: never who gave it."""

    id: UUID
    step: int = Field(ge=1, le=4)
    status: StrikeStatus
    reason: str
    given_at: datetime
    starts_at: datetime | None = None
    pause_ends_at: datetime | None = Field(
        default=None, description="When its pause ends; null for the 4th step."
    )
    verify_first_ends_at: datetime | None = None
    expires_at: datetime | None = None
    lesson_seen: bool
    can_appeal: bool
    appeal_state: AppealState
    appeal_text: str | None = None
    appeal_note: str | None = None


class ReportingStanding(BaseModel):
    """GET /report-strikes/me: whether the resident can report, and why not."""

    can_report: bool
    removed: bool = Field(description="The 4th step: no reports until an appeal is granted.")
    paused_until: datetime | None = None
    verify_first_until: datetime | None = Field(
        default=None,
        description="Until then, their report waits for staff before neighbours are alerted.",
    )
    step: int = Field(ge=0, le=4, description="The highest step in effect; 0 for none.")
    lesson_due: UUID | None = Field(
        default=None, description="A strike whose lesson the app should show once."
    )
    strikes: list[StrikeView] = Field(default_factory=list)


class StrikeGiveRequest(BaseModel):
    """The console marks one report a prank."""

    report_id: UUID
    reason: str = Field(
        min_length=3, max_length=500, description="What staff found, as the resident will read it."
    )
    serious: bool = Field(
        default=False,
        description="A truck sent out, or a real household targeted: at least the 3rd step.",
    )


class StrikeCheckRequest(BaseModel):
    """The second staff member's note, confirming or declining."""

    note: str | None = Field(default=None, max_length=500)


class StrikeAppealRequest(BaseModel):
    text: str = Field(min_length=10, max_length=500)


class StrikeAppealDecision(BaseModel):
    decision: Literal["upheld", "overturned"]
    note: str | None = Field(default=None, max_length=500)


class StrikeReviewItem(BaseModel):
    """One strike in the console's queues."""

    id: UUID
    step: int
    status: StrikeStatus
    reason: str
    serious: bool
    given_at: datetime
    given_by_name: str | None = None
    given_by_me: bool = False
    checked_by_name: str | None = None
    checked_at: datetime | None = None
    check_note: str | None = None
    starts_at: datetime | None = None
    pause_ends_at: datetime | None = None
    expires_at: datetime | None = None
    appeal_state: AppealState
    appeal_text: str | None = None
    appealed_at: datetime | None = None
    appeal_note: str | None = None
    appeal_decided_by_name: str | None = None
    appeal_decided_at: datetime | None = None
    resident_name: str | None = None
    resident_phone: str | None = Field(default=None, description="Masked: +63 9•• ••• 4567.")
    resident_strikes: int = Field(default=0, description="Strikes in effect for this person.")
    report_id: UUID | None = None
    area_id: UUID | None = None
    report_created_at: datetime | None = None
    report_lat: float | None = None
    report_lng: float | None = None
    report_notes: str | None = None
