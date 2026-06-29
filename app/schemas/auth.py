"""Authentication-related Pydantic schemas."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AuthenticatedUser(BaseModel):
    """The current authenticated user, loaded from public.users.

    Role and agency come from the database (authoritative), not the token claims,
    so privilege changes take effect immediately on the next request.
    """

    id: UUID = Field(description="User id (matches auth.users.id).")
    email: str | None = Field(default=None, description="Email, if present.")
    phone: str | None = Field(default=None, description="Phone (E.164), if present.")
    role: str = Field(description="user_role: admin | sub_admin | response_team | general_user.")
    agency_type: str | None = Field(
        default=None, description="Agency for sub-admins/response teams."
    )
    verified_percent: int = Field(
        default=0, ge=0, le=100, description="Progressive verification %."
    )
    badge: str = Field(
        default="yellow",
        description="Verification badge: yellow | light_green | green | green_check.",
    )
    full_name: str | None = Field(default=None, description="Display name.")
    primary_org_id: UUID | None = Field(default=None, description="Primary organization, if any.")
    mobile: str | None = Field(default=None, description="Contact mobile number (unverified).")
    date_of_birth: date | None = Field(default=None, description="Date of birth.")
    gender: str | None = Field(default=None, description="Gender.")


class SignupRequest(BaseModel):
    """Citizen self-signup payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None, max_length=40)


class ProfileUpdateRequest(BaseModel):
    """Editable citizen profile fields (omitted fields are left unchanged)."""

    full_name: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None, max_length=40)


class LoginRequest(BaseModel):
    """Email/password login payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Session refresh payload."""

    refresh_token: str = Field(min_length=1)


class LocationUpdateRequest(BaseModel):
    """Update the caller's last-known location (for 300 m neighborhood alerts)."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RecoverRequest(BaseModel):
    """Request a password-reset email."""

    email: EmailStr


class TokenResponse(BaseModel):
    """Session tokens returned by signup/login/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None
    user_id: UUID
    email: str | None = None