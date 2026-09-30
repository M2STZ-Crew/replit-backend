"""Live tracking as a citizen sees it (Track It Live).

Deliberately narrow. Staff watch an incident through the full IncidentDetail on
``incident:<id>``, which names responders and carries every report; a citizen
gets only this: the incident's status and position, the team that verified it,
and for each responding unit a label, its agency and where it is. No user ids,
names, phone numbers or accounts — a unit is "Unit 2" or the truck's name, and
the verifier is their brigade, never the person holding the phone.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TrackedResponder(BaseModel):
    """One responding unit: a truck, or a responder travelling without one."""

    key: str = Field(description="Stable for this incident (unit-N); not a user id.")
    label: str = Field(description="The truck's name, or 'Unit N'.")
    organization: str | None = Field(default=None, description="The responding brigade.")
    agency: str | None = Field(default=None, description="bfp | fire_volunteer | ...")
    lat: float | None = Field(
        default=None, description="Last known position; null before the first fix."
    )
    lng: float | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    accuracy_m: float | None = None
    updated_at: datetime | None = Field(
        default=None, description="When the server received the last fix."
    )
    stale: bool = Field(
        description="True when no fix arrived recently: the phone lost signal, or has not sent one."
    )


class TrackingSnapshot(BaseModel):
    """Everything Track It Live draws, in one message; each one replaces the last."""

    area_id: UUID
    designation: str
    status: str
    centroid_lat: float
    centroid_lng: float
    arrival_radius_m: float = Field(description="How close counts as on scene.")
    stale_after_seconds: int
    responders: list[TrackedResponder] = Field(
        description="Units responding. Empty unless the incident is en_route or arrived."
    )
    verified_by: str | None = Field(
        default=None,
        description="The team that verified it ('Hercules Fire Brigade'), never the person; "
        "null until verified.",
    )
    verified_by_agency: str | None = Field(
        default=None, description="That team's agency; null when an Admin verified it."
    )
    verified_at: datetime | None = None
    generated_at: datetime
