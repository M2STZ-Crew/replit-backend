"""Affiliate onboarding (organization registry) schemas (Phase 12, Section 7 #2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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


class RosterMember(BaseModel):
    """A roster entry on the public affiliation form."""

    full_name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=120)


class EquipmentUnit(BaseModel):
    """An equipment entry on the public affiliation form."""

    name: str = Field(min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=120)


class AffiliatePublicRegister(BaseModel):
    """Public affiliation form (submitted by an org with no account yet)."""

    organization_name: str = Field(min_length=1, max_length=200)
    agency_type: AgencyType
    contact_email: EmailStr
    contact_phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    roster: list[RosterMember] = Field(default_factory=list)
    equipment: list[EquipmentUnit] = Field(default_factory=list)
    sec_certificate_name: str | None = Field(default=None, max_length=300)


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
    address: str | None = None
    message: str | None = None
    status: str
    organization_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AffiliateAcceptResult(BaseModel):
    """Outcome of approving an affiliate: the request plus sub-admin provisioning."""

    request: AffiliateRequestResponse
    account_email: str | None = None
    account_provisioned: bool = False
    account_created: bool = False  # a new auth user was made (vs an existing one promoted)
    invite_email_sent: bool = False
    detail: str | None = None  # human-readable note when provisioning was partial