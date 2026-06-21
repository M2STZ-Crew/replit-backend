"""Schemas for progressive verification flows (phone in Phase 3; KYC/email in Phase 4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PhoneVerifyStartRequest(BaseModel):
    """Request to send a phone OTP."""

    phone: str = Field(
        pattern=r"^\+[1-9]\d{6,14}$",
        description="Phone in E.164 format, e.g. +639171234567.",
    )


class PhoneVerifyCheckRequest(BaseModel):
    """Submit the received phone OTP code."""

    code: str = Field(min_length=4, max_length=10, description="The SMS code received.")


class NationalIdStartResponse(BaseModel):
    """Response when a Didit National ID verification session is created."""

    session_id: str = Field(description="Didit verification session id.")
    verification_url: str = Field(description="Hosted URL where the user completes ID + selfie.")
    status: str = Field(description="Initial session status from Didit.")


class VerificationResultResponse(BaseModel):
    """Result of a verification step, with the user's updated standing."""

    verified: bool
    verified_percent: int = Field(ge=0, le=100)
    badge: str
    message: str | None = None