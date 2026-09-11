"""Post-Incident Report schemas (v10 Section 2.5).

Filed once by the responding team captain after fire out: the unit, its driver,
everyone who went, and what came off the truck. The form is single-submit with
no draft state, so the create model is the whole validation — a report that
passes it is complete, and one that does not is refused outright.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("notes")
    @classmethod
    def _blank_notes_is_none(cls, value: str | None) -> str | None:
        return value or None


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
    submitted_at: datetime
