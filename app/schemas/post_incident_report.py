"""Post-Incident Report schemas (v10 Section 2.5).

Filed once by the responding team captain after fire out: the unit, its driver,
everyone who went, and what came off the truck. The form is single-submit with
no draft state, so the create model is the whole validation — a report that
passes it is complete, and one that does not is refused outright.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RosterMember(BaseModel):
    """One person who went. ``user_id`` links an account when there is one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    user_id: UUID | None = None

    @field_validator("role")
    @classmethod
    def _blank_role_is_none(cls, value: str | None) -> str | None:
        return value or None


class PostIncidentReportCreate(BaseModel):
    """The captain's report. Every field but ``notes`` is required."""

    model_config = ConfigDict(str_strip_whitespace=True)

    truck_equipment_id: UUID | None = Field(
        default=None, description="The registered truck, when the unit is in the fleet."
    )
    truck_label: str = Field(
        min_length=1, max_length=200, description="Unit name or plate, e.g. 'Apollo'."
    )
    truck_type: str = Field(
        min_length=1, max_length=100, description="e.g. 'Fire truck', 'Water tanker'."
    )
    driver_name: str = Field(min_length=1, max_length=200)
    driver_user_id: UUID | None = None
    roster: list[RosterMember] = Field(
        min_length=1, max_length=100, description="Everyone who went, the driver included."
    )
    equipment_taken: list[str] = Field(
        min_length=1, max_length=100, description="Items taken off the unit."
    )
    notes: str | None = Field(default=None, max_length=4000)
    false_alarm: bool = Field(
        default=False,
        description=(
            "The team reached the scene and found nothing — a prank, a fire already "
            "out, or the wrong address (v11 Section 2.5.3)."
        ),
    )
    false_alarm_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why it was a false alarm. Required when false_alarm is set.",
    )

    @field_validator("equipment_taken")
    @classmethod
    def _clean_equipment(cls, items: list[str]) -> list[str]:
        """Drop blanks and repeats (case-insensitive), keeping the captain's order."""
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in items:
            text = item.strip()
            if not text:
                continue
            if len(text) > 200:
                raise ValueError("Each equipment item must be 200 characters or fewer.")
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(text)
        if not cleaned:
            raise ValueError("List at least one item taken from the unit.")
        return cleaned

    @field_validator("notes", "false_alarm_note")
    @classmethod
    def _blank_notes_is_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _false_alarm_needs_its_narrative(self) -> PostIncidentReportCreate:
        """A false alarm must say why (v11 Section 2.5.3).

        Mirrors the CHECK constraint of the same name, so the caller gets a 422
        naming the field rather than a 500 from the database. "False alarm" with
        no account of what the team actually found is the one thing this report
        exists to prevent.
        """
        if self.false_alarm and not self.false_alarm_note:
            raise ValueError(
                "Say what the team found: a false alarm needs a short explanation."
            )
        return self


class PostIncidentReportResponse(BaseModel):
    """A filed Post-Incident Report, with the incident it closed."""

    id: UUID
    area_id: UUID
    area_designation: str
    resolved_at: datetime | None = None
    filed_by: UUID | None = None
    filed_by_name: str | None = None
    filed_by_role: str
    filed_by_agency: str
    organization_id: UUID | None = None
    organization_name: str | None = None
    truck_equipment_id: UUID | None = None
    truck_label: str
    truck_type: str
    driver_name: str
    driver_user_id: UUID | None = None
    roster: list[RosterMember]
    equipment_taken: list[str]
    notes: str | None = None
    false_alarm: bool = False
    false_alarm_note: str | None = None
    submitted_at: datetime
