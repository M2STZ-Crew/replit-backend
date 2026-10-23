"""Authentication-related Pydantic schemas."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


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
    phone_verified: bool = Field(
        default=False,
        description=(
            "True once the account has verified a mobile number by SMS code. A citizen "
            "account cannot use the app until it is (see require_citizen_phone_verification)."
        ),
    )
    mobile: str | None = Field(default=None, description="Contact mobile number (unverified).")
    phone_verification_required: bool = Field(
        default=False,
        description=(
            "Set on GET /auth/me: true when this account must verify a phone before it "
            "can use the app. The app gates on this rather than on phone_verified, so "
            "turning require_citizen_phone_verification off reaches it too."
        ),
    )
    date_of_birth: date | None = Field(default=None, description="Date of birth.")
    gender: str | None = Field(default=None, description="Gender.")

    # The primary organisation's attributes, loaded with the account so access
    # checks need no second query (app/services/access.py). Never serialised:
    # GET /auth/me reports an Admin's standing as `console` instead.
    org_name: str | None = Field(default=None, exclude=True)
    org_agency_type: str | None = Field(default=None, exclude=True)
    org_is_active: bool | None = Field(default=None, exclude=True)
    org_is_central_hub: bool = Field(default=False, exclude=True)


class ConsoleOrganization(BaseModel):
    """The organisation an Admin answers for."""

    id: UUID
    name: str | None = None
    agency_type: str | None = None
    is_central_hub: bool = False


class ConsoleAccess(BaseModel):
    """What this Admin may do in the Admin console (app/services/access.py).

    ``variant`` is which of the pass 6 permission variants applies: central,
    fire_volunteer, bfp, police, medical or barangay — or ``system`` for the
    Admin account that belongs to no organisation. ``scope`` picks the
    sidebar. ``act_agencies`` are the agencies whose incidents it acknowledges
    (null: every incident); ``permissions`` are the acts the API allows it.
    """

    variant: str
    scope: str
    organization: ConsoleOrganization | None = None
    act_agencies: list[str] | None = None
    permissions: list[str] = Field(default_factory=list)


class MeResponse(AuthenticatedUser):
    """GET /auth/me: the profile, and for an Admin what it may do in the console."""

    console: ConsoleAccess | None = None


class SignupRequest(BaseModel):
    """Citizen self-signup payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Philippine mobile number, in any usual form (0917 123 4567, +63 917...). "
            "Stored as +639XXXXXXXXX. Refused if another account already verified it. "
            "Verifying it is a separate step: POST /verification/phone/request."
        ),
    )
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None, max_length=40)


class ProfileUpdateRequest(BaseModel):
    """Editable citizen profile fields (omitted fields are left unchanged)."""

    full_name: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None, max_length=40)


class LoginRequest(BaseModel):
    """Login payload: an email *or* a verified mobile number, and the password."""

    email: EmailStr | None = Field(default=None, description="The account's email.")
    phone: str | None = Field(
        default=None,
        min_length=10,
        max_length=20,
        description=(
            "A mobile number verified on the account, in any usual form. Only a "
            "verified number signs in: an unverified one proves nothing about who "
            "owns it."
        ),
    )
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> LoginRequest:
        if (self.email is None) == (self.phone is None):
            raise ValueError("Sign in with either an email or a mobile number.")
        return self


class RefreshRequest(BaseModel):
    """Session refresh payload."""

    refresh_token: str = Field(min_length=1)


class LocationUpdateRequest(BaseModel):
    """Update the caller's last-known location (for 150 m neighborhood alerts)."""

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