"""The Admin Dashboard's statistics (v1.12.50; app/services/incident_statistics.py)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

StatisticsScope = Literal["org", "all"]


class CountStatistic(BaseModel):
    """A count, and the same for the previous period when it can be compared."""

    value: int = 0
    previous: int | None = None


class MeasureStatistic(BaseModel):
    """A median or a share, the fires it rests on, and the previous period's."""

    value: float | None = None
    n: int = 0
    previous: float | None = None


class DayCount(BaseModel):
    """One Manila day's fires."""

    day: date
    count: int


class BarangayCount(BaseModel):
    """One barangay's fires; its city tells Pasay's Barangay 76 from Manila's."""

    pcode: str
    name: str
    city: str | None = None
    count: int


class KeyCount(BaseModel):
    """One alarm level's or fire type's fires; ``key`` is None for none yet."""

    key: str | None = None
    count: int


class IncidentStatistics(BaseModel):
    """7, 30 or 90 days of fires, against the same length of time before."""

    days: int
    scope: StatisticsScope
    start: datetime = Field(description="Midnight in Manila that began the period.")
    end: datetime
    records_since: datetime | None = Field(
        default=None, description="The first fire on record: production was reset 13 Nov 2026."
    )
    comparable: bool = Field(
        default=False,
        description="The records cover the previous period; without, no change is given.",
    )
    minutes_to_acknowledge: MeasureStatistic
    minutes_to_scene: MeasureStatistic
    fires: CountStatistic
    false_alarms: MeasureStatistic
    per_day: list[DayCount]
    barangays: list[BarangayCount]
    without_barangay: int = 0
    alarm_levels: list[KeyCount]
    fire_types: list[KeyCount]
