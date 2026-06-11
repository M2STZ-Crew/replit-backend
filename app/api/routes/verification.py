"""Progressive verification endpoints. Phase 3: phone OTP (+40%)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseDep, TwilioVerifyDep
from app.core.config import get_settings
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.verification import (
    PhoneVerifyCheckRequest,
    PhoneVerifyStartRequest,
    VerificationResultResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/phone/request", response_model=MessageResponse, summary="Request phone OTP")
async def request_phone_otp(
    payload: PhoneVerifyStartRequest,
    user: CurrentUser,
    db: DatabaseDep,
    twilio: TwilioVerifyDep,
) -> MessageResponse:
    """Send an SMS OTP and record a pending phone verification for the current user."""
    await twilio.start_verification(payload.phone)
    await db.execute(
        """
        insert into public.user_verifications (user_id, type, status, provider, metadata)
        values ($1, 'phone', 'pending', 'twilio', jsonb_build_object('phone', $2::text))
        on conflict (user_id, type) do update
           set status = 'pending',
               provider = 'twilio',
               metadata = public.user_verifications.metadata
                          || jsonb_build_object('phone', $2::text),
               submitted_at = now()
        """,
        user.id,
        payload.phone,
    )
    log.info("phone_otp_requested", user_id=str(user.id))
    return MessageResponse(message="Verification code sent via SMS.")


@router.post(
    "/phone/verify",
    response_model=VerificationResultResponse,
    summary="Verify phone OTP (+40%)",
)
async def verify_phone_otp(
    payload: PhoneVerifyCheckRequest,
    user: CurrentUser,
    db: DatabaseDep,
    twilio: TwilioVerifyDep,
) -> VerificationResultResponse:
    """Check the OTP; on success mark phone verified (+40%) and update the profile."""
    settings = get_settings()
    row = await db.fetchrow(
        """
        select metadata->>'phone' as phone
        from public.user_verifications
        where user_id = $1 and type = 'phone'
        """,
        user.id,
    )
    phone = row["phone"] if row else None
    if not phone:
        raise BadRequestError("No phone verification in progress; request a code first.")

    approved = await twilio.check_verification(phone, payload.code)
    if not approved:
        raise BadRequestError("Incorrect or expired verification code.")

    await db.execute(
        """
        update public.user_verifications
           set status = 'verified', percent_awarded = $2, verified_at = now()
         where user_id = $1 and type = 'phone'
        """,
        user.id,
        settings.phone_verification_percent,
    )
    await db.execute("update public.users set phone = $2 where id = $1", user.id, phone)

    result = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", user.id
    )
    assert result is not None  # the user row always exists for an authenticated user
    log.info("phone_verified", user_id=str(user.id))
    return VerificationResultResponse(
        verified=True,
        verified_percent=result["verified_percent"],
        badge=str(result["badge"]),
        message="Phone verified (+40%).",
    )