"""Authentication-related Pydantic schemas."""

from __future__ import annotations

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
    full_name: str | None = Field(default=None, description="Display name.")
    primary_org_id: UUID | None = Field(default=None, description="Primary organization, if any.")


class SignupRequest(BaseModel):
    """Citizen self-signup payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    """Email/password login payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Session refresh payload."""

    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Session tokens returned by signup/login/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None
    user_id: UUID
    email: str | None = None