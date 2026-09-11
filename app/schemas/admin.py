"""Admin user-management and verification-review schemas (Section 6 RBAC)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

UserRoleLiteral = Literal["admin", "sub_admin", "response_team", "general_user"]
AgencyLiteral = Literal["fire_volunteer", "bfp", "barangay", "medical", "police"]


class AdminCreateUserRequest(BaseModel):
    """Admin-create a user with an assigned role and (for staff) an agency."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    role: UserRoleLiteral
    agency_type: AgencyLiteral | None = None
    primary_org_id: UUID | None = None

    @model_validator(mode="after")
    def _check_agency_consistency(self) -> AdminCreateUserRequest:
        """Mirror the DB CHECK: staff roles need an agency; others must not have one."""
        is_staff_role = self.role in ("sub_admin", "response_team")
        if is_staff_role and self.agency_type is None:
            raise ValueError("agency_type is required for sub_admin and response_team roles.")
        if not is_staff_role and self.agency_type is not None:
            raise ValueError("agency_type must be empty for admin and general_user roles.")
        return self


class PendingVerification(BaseModel):
    """A verification awaiting Admin manual review."""

    id: UUID
    user_id: UUID
    email: str | None = None
    full_name: str | None = None
    type: str
    status: str
    provider: str | None = None
    submitted_at: datetime
    id_image_url: str | None = None
    selfie_image_url: str | None = None


class VerificationReviewRequest(BaseModel):
    """Optional notes when rejecting a verification."""

    notes: str | None = Field(default=None, max_length=1000)


class RouteTarget(BaseModel):
    """One agency to route an incident to, and which of its teams to alert."""

    agency: AgencyLiteral
    organization_ids: list[UUID] = Field(
        default_factory=list,
        max_length=20,
        description="Teams within the agency to alert; empty routes to the agency as a whole.",
    )

    @field_validator("organization_ids")
    @classmethod
    def _dedupe(cls, ids: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(ids))


class RouteIncidentRequest(BaseModel):
    """Admin accepts an incoming incident and routes it (v10 Section 2.6.2).

    Several agencies at once is the normal case for a large fire — Fire
    Volunteer, Medical and Police together.
    """

    routes: list[RouteTarget] = Field(min_length=1, max_length=5)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _one_entry_per_agency(self) -> RouteIncidentRequest:
        agencies = [route.agency for route in self.routes]
        if len(agencies) != len(set(agencies)):
            raise ValueError("List each agency once; put all of its teams in one entry.")
        return self