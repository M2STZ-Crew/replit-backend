"""Schemas for "New Update!" (app/workers/app_updates.py)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppUpdateCheckResponse(BaseModel):
    """What an asked-for check found: the newest release only.

    How many people were told stays in the service's log: the ask is public.
    """

    version: str | None = Field(
        description=(
            "The newest Android release (its latest.json), or null when it "
            "could not be read just now."
        ),
        examples=["1.12.41"],
    )
