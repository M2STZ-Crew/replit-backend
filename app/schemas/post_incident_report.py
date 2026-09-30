"""Post-Incident Report schemas (v10 Section 2.5).

Filed once by the responding team captain after fire out: when it happened and
when the fire was out, the units that went, the driver, everyone who went, and
what came off the trucks. Every answer is a selection - the app offers the
organisation's units, members and equipment to pick from, so nothing is typed.

The form is single-submit with no draft state, so the create model is the whole
validation: a report that passes it is complete, and one that does not is
refused outright.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# A phone's clock is rarely exact; this much "in the future" is tolerated.
_CLOCK_SKEW = timedelta(minutes=5)


def _aware(value: datetime | None) -> datetime | None:
    """A timestamp with no zone is taken as UTC, so comparisons never raise."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ReportUnit(BaseModel):
    """One unit that went. ``equipment_id`` links the registered unit when there is one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200, description="e.g. 'Apollo'.")
    type: str | None = Field(default=None, max_length=100, description="e.g. 'Fire Truck'.")
    equipment_id: UUID | None = None

    @field_validator("type")
    @classmethod
    def _blank_type_is_none(cls, value: str | None) -> str | None:
        return value or None


class RosterMember(BaseModel):
    """One person who went. ``user_id`` links an account when there is one.

    ``role`` is no longer asked for; it stays so reports filed before it was
    dropped still read back whole.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    user_id: UUID | None = None

    @field_validator("role")
    @classmethod
    def _blank_role_is_none(cls, value: str | None) -> str | None:
        return value or None


class PostIncidentReportCreate(BaseModel):
    """The captain's report. Everything but the two times is required.

    The times default to what the system recorded - when the first report came
    in and when fire out was declared - so the captain only changes them if the
    record is off.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    incident_at: datetime | None = Field(
        default=None, description="When the incident happened. Defaults to the first report."
    )
    fire_out_at: datetime | None = Field(
        default=None, description="When the fire was out. Defaults to when it was declared."
    )
    units: list[ReportUnit] = Field(
        min_length=1, max_length=20, description="Every unit that went."
    )
    driver_name: str = Field(min_length=1, max_length=200)
    driver_user_id: UUID | None = None
    roster: list[RosterMember] = Field(
        min_length=1, max_length=100, description="Everyone who went, the driver included."
    )
    equipment_taken: list[str] = Field(
        min_length=1, max_length=100, description="Items taken off the units."
    )
    # Not asked for any more (the form is selection-only). Accepted so an app
    # build from before the change can still file.
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

    @model_validator(mode="before")
    @classmethod
    def _one_truck_is_one_unit(cls, data: Any) -> Any:
        """Accept the single-truck shape app builds before this change send.

        They post ``truck_label`` / ``truck_type`` / ``truck_equipment_id`` and
        no ``units``. Refusing that would stop every captain who has not
        updated from closing an incident.
        """
        if isinstance(data, dict) and not data.get("units") and data.get("truck_label"):
            data = dict(data)
            data["units"] = [
                {
                    "name": data["truck_label"],
                    "type": data.get("truck_type"),
                    "equipment_id": data.get("truck_equipment_id"),
                }
            ]
        return data

    @field_validator("incident_at", "fire_out_at")
    @classmethod
    def _times_are_not_ahead_of_now(cls, value: datetime | None) -> datetime | None:
        value = _aware(value)
        if value is not None and value > datetime.now(UTC) + _CLOCK_SKEW:
            raise ValueError("That time has not happened yet.")
        return value

    @field_validator("units")
    @classmethod
    def _no_unit_twice(cls, units: list[ReportUnit]) -> list[ReportUnit]:
        seen: set[str] = set()
        kept: list[ReportUnit] = []
        for unit in units:
            key = str(unit.equipment_id) if unit.equipment_id else unit.name.casefold()
            if key not in seen:
                seen.add(key)
                kept.append(unit)
        return kept

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
    def _the_fire_is_out_after_it_started(self) -> PostIncidentReportCreate:
        if (
            self.incident_at is not None
            and self.fire_out_at is not None
            and self.fire_out_at < self.incident_at
        ):
            raise ValueError("The fire cannot be out before the incident happened.")
        return self

    @model_validator(mode="after")
    def _false_alarm_needs_its_narrative(self) -> PostIncidentReportCreate:
        """A false alarm must say why (v11 Section 2.5.3).

        Mirrors the CHECK constraint of the same name, so the caller gets a 422
        naming the field rather than a 500 from the database. "False alarm" with
        no account of what the team actually found is the one thing this report
        exists to prevent. The app offers the reasons to pick from.
        """
        if self.false_alarm and not self.false_alarm_note:
            raise ValueError(
                "Say what the team found: a false alarm needs a short explanation."
            )
        return self

    @property
    def unit_names(self) -> str:
        """The units as one line - what the NOT NULL truck_label column holds."""
        return ", ".join(u.name for u in self.units)

    @property
    def unit_types(self) -> str:
        """The distinct unit types as one line, for the truck_type column."""
        types: list[str] = []
        for unit in self.units:
            label = unit.type or "Unit"
            if label not in types:
                types.append(label)
        return ", ".join(types)


class PostIncidentReportResponse(BaseModel):
    """A filed Post-Incident Report, with the incident it closed."""

    id: UUID
    area_id: UUID
    area_designation: str
    resolved_at: datetime | None = None
    incident_at: datetime | None = None
    fire_out_at: datetime | None = None
    filed_by: UUID | None = None
    filed_by_name: str | None = None
    filed_by_role: str
    filed_by_agency: str
    organization_id: UUID | None = None
    organization_name: str | None = None
    units: list[ReportUnit] = Field(default_factory=list)
    # The units joined into one line; kept for clients that read a single truck.
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
