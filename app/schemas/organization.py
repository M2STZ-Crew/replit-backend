"""Affiliate organization directory schemas (admin web "Affiliate Organizations").

Read-only views over public.organizations plus their personnel (public.users by
primary_org_id). Equipment is served by the existing /equipment endpoint.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
    personnel_count: int = 0
    equipment_count: int = 0
    created_at: datetime


class OrganizationMember(BaseModel):
    """A personnel record (a user assigned to the organization)."""

    id: UUID
    full_name: str | None = None
    role: str
    agency_type: str | None = None
    verified_percent: int = 0
    badge: str | None = None
