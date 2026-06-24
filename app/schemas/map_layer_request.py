"""Map-layer update request schemas (Phase 12, Section 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

LayerType = Literal[
    "hydrant", "evacuation_site", "risk_zone", "bodies_of_water",
    "underground_cistern", "equipment",
]
Operation = Literal["create", "update", "delete"]


class MapLayerRequestCreate(BaseModel):
    """Propose a create/update/delete change to a map layer or equipment record."""

    layer_type: LayerType
    operation: Operation
    target_id: UUID | None = None
    proposed_data: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_target(self) -> MapLayerRequestCreate:
        """Mirror the DB CHECK: update/delete must name a target_id."""
        if self.operation in ("update", "delete") and self.target_id is None:
            raise ValueError("target_id is required for update and delete operations.")
        return self


class MapLayerReviewRequest(BaseModel):
    """Optional reviewer notes when approving/rejecting."""

    notes: str | None = Field(default=None, max_length=1000)


class MapLayerRequestResponse(BaseModel):
    """A map-layer update request row."""

    id: UUID
    requested_by: UUID | None = None
    organization_id: UUID | None = None
    layer_type: str
    operation: str
    target_id: UUID | None = None
    proposed_data: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    status: str
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime