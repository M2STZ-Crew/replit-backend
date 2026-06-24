"""Equipment inventory schemas (Phase 12, Section 7 #21)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

EquipmentStatus = Literal["available", "in_use", "maintenance", "out_of_service"]


class EquipmentCreate(BaseModel):
    """Create an equipment item under an organization."""

    organization_id: UUID
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=0)
    status: EquipmentStatus = "available"
    serial_number: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    last_serviced_at: datetime | None = None


class EquipmentUpdate(BaseModel):
    """Patch an equipment item (only the provided fields change)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=0)
    status: EquipmentStatus | None = None
    serial_number: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    last_serviced_at: datetime | None = None


class EquipmentResponse(BaseModel):
    """An equipment inventory row."""

    id: UUID
    organization_id: UUID
    name: str
    category: str | None = None
    quantity: int
    status: str
    serial_number: str | None = None
    description: str | None = None
    last_serviced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime