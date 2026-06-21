"""Admin user-management and verification-review schemas (Section 6 RBAC)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

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