"""Affiliate organization directory schemas (admin web "Affiliate Organizations").

Read-only views over public.organizations plus their personnel (public.users by
primary_org_id). Equipment is served by the existing /equipment endpoint.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OrganizationSummary(BaseModel):
    """An affiliate organization with personnel/equipment counts."""

    id: UUID
    name: str
    agency_type: str
    description: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    is_active: bool
    # The central hub (Barangay 76): its Admins also review affiliates and IDs.
    is_central_hub: bool = False
    personnel_count: int = 0
    equipment_count: int = 0
    created_at: datetime


class OrganizationMember(BaseModel):
    """A personnel record (a user assigned to the organization).

    The account fields after ``badge`` are filled for an Admin reading its
    organisation's roster (GET /organizations/{id}/personnel): what the
    Accounts screen lists and acts on. The mobile members list leaves them out.
    """

    id: UUID
    full_name: str | None = None
    role: str
    agency_type: str | None = None
    verified_percent: int = 0
    badge: str | None = None
    email: str | None = None
    title: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    created_by_name: str | None = None
    deactivated_at: datetime | None = None


class CoordinatorCreateRequest(BaseModel):
    """An Admin creates a Coordinator for its organisation (PRD §4.6.4, pass 6 A49).

    The sign-in address is made from the name, the organisation's agency and
    the role (obryan.fircor@replit.com; app/services/responder_accounts.py).
    ``personal_email`` is the Coordinator's own, where the link that confirms it
    and sets their password goes, and later password resets: @replit.com has no
    mailboxes. ``organization_id`` is for the system Admin, which belongs to no
    organisation; an organisation's Admin always creates into its own.
    """

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60, description="The full surname.")
    personal_email: EmailStr
    title: str | None = Field(default=None, max_length=80)
    organization_id: UUID | None = None


class CoordinatorCreateResult(BaseModel):
    """The new Coordinator, and whether the email to their personal address went out."""

    coordinator: OrganizationMember
    personal_email: str | None = None
    invite_email_sent: bool = False
    detail: str | None = None


class CoordinatorEmailPreview(BaseModel):
    """The address a new Coordinator with this name would get."""

    email: str
