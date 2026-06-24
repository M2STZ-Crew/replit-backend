"""Affiliate onboarding (organization registry) schemas (Phase 12, Section 7 #2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

AgencyType = Literal["fire_volunteer", "bfp", "barangay", "medical", "police"]


class AffiliateRequestCreate(BaseModel):
    """Submit an organization onboarding request."""

    organization_name: str = Field(min_length=1, max_length=200)
    agency_type: AgencyType
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)


class AffiliateReviewRequest(BaseModel):
    """Optional reviewer notes when approving/rejecting."""

    notes: str | None = Field(default=None, max_length=1000)


class AffiliateRequestResponse(BaseModel):
    """An affiliate onboarding request row."""

    id: UUID
    organization_name: str
    agency_type: str
    requested_by: UUID | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    message: str | None = None
    status: str
    organization_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    created_at: datetime
    updated_at: datetime