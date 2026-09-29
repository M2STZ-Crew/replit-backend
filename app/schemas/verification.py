"""Schemas for progressive verification flows (phone in Phase 3; KYC/email in Phase 4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PhoneVerifyStartRequest(BaseModel):
    """Request to text a verification code to a Philippine mobile number."""

    phone: str = Field(
        min_length=10,
        max_length=20,
        description=(
            "A Philippine mobile number in any common form: 0917 123 4567, "
            "09171234567, +639171234567 or 639171234567. Normalised server-side."
        ),
    )


class PhoneCodeRequestResponse(BaseModel):
    """What asking for a code came to.

    ``message`` stays first so a client that only reads it keeps working. The
    two timers let a client count down the resend button and the code's life.
    """

    message: str
    phone: str = Field(description="The number the code went to, normalised to E.164.")
    sent: bool = Field(description="False when the number was already verified.")
    expires_in_seconds: int = Field(ge=0)
    resend_after_seconds: int = Field(ge=0)


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


class VerificationChannelStatus(BaseModel):
    """State of one verification channel for the caller."""

    type: str = Field(description="'phone', 'email', or 'national_id'.")
    status: str = Field(
        description="pending | verified | manual_review | rejected | failed."
    )
    percent_awarded: int = Field(ge=0, le=100)
    submitted_at: datetime | None = None
    verified_at: datetime | None = None
    review_notes: str | None = Field(
        default=None, description="Reviewer's reason, set when a KYC review rejects."
    )


class VerificationStatusResponse(BaseModel):
    """The caller's progressive-verification standing, per channel.

    ``verified_percent`` alone cannot distinguish "never submitted" from
    "submitted and awaiting Admin review" — both read as 0 for that channel — so
    a client showing an upload form would prompt a user to submit again while
    their first submission still sits in the queue.
    """

    verified_percent: int = Field(ge=0, le=100)
    badge: str
    channels: list[VerificationChannelStatus] = Field(default_factory=list)