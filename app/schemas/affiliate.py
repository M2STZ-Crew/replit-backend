"""Affiliate onboarding (organization registry) schemas (Phase 12, Section 7 #2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, EmailStr, Field

from app.services.names import one_line

AgencyType = Literal["fire_volunteer", "bfp", "barangay", "medical", "police"]

# What the public form types, as one line (v1.12.51).
Line = Annotated[str, BeforeValidator(lambda v: one_line(v) if isinstance(v, str) else v)]
OptionalLine = Annotated[
    str | None, BeforeValidator(lambda v: (one_line(v) or None) if isinstance(v, str) else v)
]
# The most a public application may list.
MAX_ROSTER = 200
MAX_EQUIPMENT = 100


class AffiliateRequestCreate(BaseModel):
    """Submit an organization onboarding request."""

    organization_name: Line = Field(min_length=1, max_length=200)
    agency_type: AgencyType
    contact_name: OptionalLine = Field(default=None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: OptionalLine = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)


class RosterMember(BaseModel):
    """A roster entry on the public affiliation form."""

    full_name: Line = Field(min_length=1, max_length=200)
    role: OptionalLine = Field(default=None, max_length=120)


class EquipmentUnit(BaseModel):
    """An equipment entry on the public affiliation form."""

    name: Line = Field(min_length=1, max_length=200)
    type: OptionalLine = Field(default=None, max_length=120)


class AffiliatePublicRegister(BaseModel):
    """Public affiliation form (submitted by an org with no account yet)."""

    organization_name: Line = Field(min_length=1, max_length=200)
    agency_type: AgencyType
    contact_email: EmailStr
    # The person who becomes the first Coordinator (v1.12.51); an older page
    # sends none, and the hub then types the name as it accepts.
    contact_first_name: OptionalLine = Field(default=None, max_length=60)
    contact_last_name: OptionalLine = Field(default=None, max_length=60)
    contact_phone: OptionalLine = Field(default=None, max_length=40)
    address: OptionalLine = Field(default=None, max_length=500)
    roster: list[RosterMember] = Field(default_factory=list, max_length=MAX_ROSTER)
    equipment: list[EquipmentUnit] = Field(default_factory=list, max_length=MAX_EQUIPMENT)
    sec_certificate_name: OptionalLine = Field(default=None, max_length=300)


class AffiliateReviewRequest(BaseModel):
    """Optional reviewer notes when approving/rejecting."""

    notes: str | None = Field(default=None, max_length=1000)


class AffiliateAcceptRequest(AffiliateReviewRequest):
    """Accepting: notes, and the first Coordinator's name if the form's is not it."""

    coordinator_first_name: OptionalLine = Field(default=None, max_length=60)
    coordinator_last_name: OptionalLine = Field(default=None, max_length=60)


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
    # Only on the public form's answer: uploads its SEC certificate (v1.12.53).
    certificate_upload_token: str | None = None


class AffiliateAcceptResult(BaseModel):
    """Outcome of approving an affiliate: the request and its new Coordinator."""

    request: AffiliateRequestResponse
    account_email: str | None = None  # where the password link goes
    sign_in_address: str | None = None  # the new Coordinator's @replit.com sign-in
    account_provisioned: bool = False
    account_created: bool = False  # always a new account, never one promoted (v1.12.51)
    invite_email_sent: bool = False
    detail: str | None = None  # human-readable note when provisioning was partial
    admin_link_sent: bool = False  # the one-time Admin registration link (v1.12.53)


class CertificateLink(BaseModel):
    """A short-lived link to an application's SEC certificate."""

    url: str


class AdminRegistrationLink(BaseModel):
    """What the console's /admin-registration page shows (v1.12.53)."""

    state: Literal["valid", "expired", "used"]
    organization: str
    expires_at: datetime
    suffix: str
    prefix_help: str


class AdminPrefixStatus(BaseModel):
    status: Literal["available", "taken", "not_allowed"]


class AdminRegistrationCreate(BaseModel):
    token: str = Field(min_length=10, max_length=1000)
    prefix: str = Field(min_length=1, max_length=60)


class AdminRegistrationDone(BaseModel):
    email: str
    sent_to: str
    invite_email_sent: bool = False
