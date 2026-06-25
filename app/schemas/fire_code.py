"""Fire code schemas (Phase 13, Section 7 #17-#18)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FireCodeResponse(BaseModel):
    """A fire code from the catalog."""

    id: UUID
    code_number: str
    name: str
    description: str | None = None
    target_role: str
    target_agency: str | None = None
    is_active: bool
    display_order: int


class FireCodePressRequest(BaseModel):
    """Press a fire code, optionally tied to an incident."""

    area_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class FireCodeEventResponse(BaseModel):
    """A logged fire-code press."""

    id: UUID
    fire_code_id: UUID
    code_number: str
    name: str
    area_id: UUID | None = None
    pressed_by: UUID | None = None
    pressed_at: datetime
    notes: str | None = None