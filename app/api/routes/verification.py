"""Progressive verification endpoints.

Phase 3: phone OTP (+40%). Phase 4: Didit.me National ID KYC (+50%) via a hosted
session, with a poll/refresh path and an HMAC-verified webhook. Approved => +50%;
Declined / In Review => routed to the Admin manual-review queue (Section 3.2).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import HTMLResponse

from app.api.deps import (
    CurrentUser,
    DatabaseDep,
    DiditClientDep,
    EmailClientDep,
    StorageClientDep,
    TwilioVerifyDep,
)
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ExternalServiceError, UnauthorizedError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.common import MessageResponse
from app.schemas.verification import (
    NationalIdStartResponse,
    PhoneVerifyCheckRequest,
    PhoneVerifyStartRequest,
    VerificationChannelStatus,
    VerificationResultResponse,
    VerificationStatusResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get(
    "/status",
    response_model=VerificationStatusResponse,
    summary="My progressive-verification standing, per channel",
)
async def verification_status(
    user: CurrentUser, db: DatabaseDep
) -> VerificationStatusResponse:
    """Return the caller's percent, badge, and the state of each channel.

    A client needs the per-channel status to tell "never submitted" apart from
    "submitted, awaiting Admin review" — both contribute 0% — otherwise it
    prompts the user to upload their National ID again while the first
    submission is still in the review queue.
    """
    rows = await db.fetch(
        """
        select type::text as type, status::text as status, percent_awarded,
               submitted_at, verified_at, review_notes
        from public.user_verifications
        where user_id = $1
        order by type
        """,
        user.id,
    )
    profile = await db.fetchrow(
        "select verified_percent, badge::text as badge from public.users where id = $1",
        user.id,
    )
    if profile is None:
        raise BadRequestError("Profile not found.")
    return VerificationStatusResponse(
        verified_percent=profile["verified_percent"],
        badge=profile["badge"],
        channels=[VerificationChannelStatus.model_validate(dict(r)) for r in rows],
    )


# --------------------------------------------------------------------------- #
# Phone OTP (+40%)
# --------------------------------------------------------------------------- #
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
    assert result is not None
    log.info("phone_verified", user_id=str(user.id))
    return VerificationResultResponse(
        verified=True,
        verified_percent=result["verified_percent"],
        badge=str(result["badge"]),
        message="Phone verified (+40%).",
    )


# --------------------------------------------------------------------------- #
# National ID KYC (+50%) — Didit.me
# --------------------------------------------------------------------------- #
async def _apply_didit_decision(db: Database, *, session_id: str, status_text: str) -> None:
    """Update the national_id verification from a Didit status (Approved => +50%)."""
    settings = get_settings()
    state = (status_text or "").strip().lower()
    if state == "approved":
        await db.execute(
            """
            update public.user_verifications
               set status = 'verified', percent_awarded = $2, verified_at = now(),
                   metadata = metadata || jsonb_build_object('didit_status', $3::text)
             where provider_reference = $1 and type = 'national_id'
            """,
            session_id,
            settings.id_verification_percent,
            status_text,
        )
    elif state in ("declined", "in review", "in_review"):
        await db.execute(
            """
            update public.user_verifications
               set status = 'manual_review',
                   metadata = metadata || jsonb_build_object('didit_status', $2::text)
             where provider_reference = $1 and type = 'national_id'
            """,
            session_id,
            status_text,
        )
    else:
        await db.execute(
            """
            update public.user_verifications
               set metadata = metadata || jsonb_build_object('didit_status', $2::text)
             where provider_reference = $1 and type = 'national_id'
            """,
            session_id,
            status_text,
        )


@router.post(
    "/national-id/start",
    response_model=NationalIdStartResponse,
    summary="Start National ID KYC (Didit session)",
)
async def start_national_id(
    user: CurrentUser, db: DatabaseDep, didit: DiditClientDep
) -> NationalIdStartResponse:
    """Create a Didit verification session and return its hosted URL."""
    settings = get_settings()
    session = await didit.create_session(
        user_id=str(user.id), callback_url=settings.public_base_url
    )
    session_id = session.get("session_id")
    url = session.get("url")
    if not isinstance(session_id, str) or not isinstance(url, str):
        raise ExternalServiceError("Verification provider returned an incomplete session.")
    await db.execute(
        """
        insert into public.user_verifications
            (user_id, type, status, provider, provider_reference, metadata)
        values ($1, 'national_id', 'pending', 'didit', $2,
                jsonb_build_object('session_id', $2::text, 'verification_url', $3::text))
        on conflict (user_id, type) do update
           set status = 'pending', provider = 'didit', provider_reference = $2,
               metadata = public.user_verifications.metadata || jsonb_build_object(
               'session_id', $2::text, 'verification_url', $3::text),
               submitted_at = now(), verified_at = null
        """,
        user.id,
        session_id,
        url,
    )
    log.info("national_id_session_started", user_id=str(user.id))
    return NationalIdStartResponse(
        session_id=session_id,
        verification_url=url,
        status=str(session.get("status", "Not Started")),
    )


@router.post(
    "/national-id/refresh",
    response_model=VerificationResultResponse,
    summary="Poll National ID KYC decision",
)
async def refresh_national_id(
    user: CurrentUser, db: DatabaseDep, didit: DiditClientDep
) -> VerificationResultResponse:
    """Poll Didit for the latest decision and apply it (dev-friendly, no webhook needed)."""
    row = await db.fetchrow(
        """
        select provider_reference
        from public.user_verifications
        where user_id = $1 and type = 'national_id'
        """,
        user.id,
    )
    session_id = row["provider_reference"] if row else None
    if not session_id:
        raise BadRequestError("No identity verification in progress; start one first.")

    decision = await didit.retrieve_decision(session_id=str(session_id))
    status_text = str(decision.get("status") or "")
    await _apply_didit_decision(db, session_id=str(session_id), status_text=status_text)

    user_row = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", user.id
    )
    ver_row = await db.fetchrow(
        "select status from public.user_verifications where user_id = $1 and type = 'national_id'",
        user.id,
    )
    assert user_row is not None
    return VerificationResultResponse(
        verified=bool(ver_row is not None and ver_row["status"] == "verified"),
        verified_percent=user_row["verified_percent"],
        badge=str(user_row["badge"]),
        message=f"Verification status: {status_text}",
    )


@router.post("/national-id/webhook", summary="Didit KYC webhook (HMAC-verified)")
async def national_id_webhook(
    request: Request, db: DatabaseDep, didit: DiditClientDep
) -> Response:
    """Receive a Didit decision webhook, verify its HMAC signature, and apply it."""
    raw = await request.body()
    if not didit.verify_webhook(
        raw_body=raw,
        signature=request.headers.get("x-signature", ""),
        timestamp=request.headers.get("x-timestamp", ""),
    ):
        raise UnauthorizedError("Invalid webhook signature.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError("Invalid webhook payload.") from exc
    session_id = payload.get("session_id")
    status_text = str(payload.get("status") or "")
    if isinstance(session_id, str):
        await _apply_didit_decision(db, session_id=session_id, status_text=status_text)
    log.info("didit_webhook_received", session_id=session_id, status=status_text)
    return Response(status_code=200)

# --------------------------------------------------------------------------- #
# National ID manual upload (Admin-review fallback — no Didit credits needed)
# --------------------------------------------------------------------------- #
_MAX_ID_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}


async def _read_validated_image(upload: UploadFile) -> tuple[bytes, str]:
    """Validate an uploaded image (type + size); return (bytes, extension)."""
    ext = _ALLOWED_IMAGE_TYPES.get(upload.content_type or "")
    if ext is None:
        raise BadRequestError("Only JPEG or PNG images are accepted.")
    content = await upload.read()
    if len(content) == 0:
        raise BadRequestError("Uploaded image is empty.")
    if len(content) > _MAX_ID_IMAGE_BYTES:
        raise BadRequestError("Image exceeds the 10 MB limit.")
    return content, ext


@router.post(
    "/national-id/manual",
    response_model=VerificationResultResponse,
    summary="Submit National ID + selfie for Admin manual review",
)
async def submit_national_id_manual(
    user: CurrentUser,
    db: DatabaseDep,
    storage: StorageClientDep,
    id_image: Annotated[UploadFile, File(description="National ID photo (JPEG/PNG, <=10MB)")],
    selfie_image: Annotated[UploadFile, File(description="Matching selfie (JPEG/PNG, <=10MB)")],
) -> VerificationResultResponse:
    """Store the ID + selfie privately and queue the user for Admin manual review."""
    id_bytes, id_ext = await _read_validated_image(id_image)
    selfie_bytes, selfie_ext = await _read_validated_image(selfie_image)

    id_path = f"{user.id}/national_id{id_ext}"
    selfie_path = f"{user.id}/selfie{selfie_ext}"
    await storage.upload(
        bucket="national-ids",
        path=id_path,
        content=id_bytes,
        content_type=id_image.content_type or "image/jpeg",
    )
    await storage.upload(
        bucket="national-ids",
        path=selfie_path,
        content=selfie_bytes,
        content_type=selfie_image.content_type or "image/jpeg",
    )
    await db.execute(
        """
        insert into public.user_verifications (user_id, type, status, provider, metadata)
        values ($1, 'national_id', 'manual_review', 'manual',
                jsonb_build_object('id_path', $2::text, 'selfie_path', $3::text))
        on conflict (user_id, type) do update
           set status = 'manual_review', provider = 'manual',
               metadata = public.user_verifications.metadata
                          || jsonb_build_object('id_path', $2::text, 'selfie_path', $3::text),
               submitted_at = now(), verified_at = null
        """,
        user.id,
        id_path,
        selfie_path,
    )
    result = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", user.id
    )
    assert result is not None
    log.info("national_id_manual_submitted", user_id=str(user.id))
    return VerificationResultResponse(
        verified=False,
        verified_percent=result["verified_percent"],
        badge=str(result["badge"]),
        message="National ID submitted for admin review.",
    )

# --------------------------------------------------------------------------- #
# Email verification (+10%) — Brevo link-based
# --------------------------------------------------------------------------- #
@router.post(
    "/email/request",
    response_model=MessageResponse,
    summary="Send an email verification link (+10%)",
)
async def request_email_verification(
    user: CurrentUser, db: DatabaseDep, email: EmailClientDep
) -> MessageResponse:
    """Generate a one-time link and email it to the user's address."""
    settings = get_settings()
    if not user.email:
        raise BadRequestError("Your account has no email address to verify.")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    await db.execute(
        """
        insert into public.user_verifications (user_id, type, status, provider, metadata)
        values ($1, 'email', 'pending', 'brevo',
                jsonb_build_object('token_hash', $2::text, 'expires_at', $3::text))
        on conflict (user_id, type) do update
           set status = 'pending', provider = 'brevo',
               metadata = public.user_verifications.metadata
                          || jsonb_build_object('token_hash', $2::text, 'expires_at', $3::text),
               submitted_at = now(), verified_at = null
        """,
        user.id,
        token_hash,
        expires_at,
    )
    link = f"{settings.public_base_url.rstrip('/')}/verification/email/confirm?token={token}"
    html = (
        f"<p>Hi {user.full_name or 'there'},</p>"
        "<p>Confirm your email for RepLiT (link valid for 24 hours):</p>"
        f'<p><a href="{link}">Verify my email</a></p>'
        f"<p>Or paste this URL into your browser:<br>{link}</p>"
    )
    await email.send(to=user.email, subject="Verify your RepLiT email", html=html)
    log.info("email_verification_requested", user_id=str(user.id))
    return MessageResponse(message="Verification email sent. Check your inbox.")


@router.get(
    "/email/confirm",
    response_class=HTMLResponse,
    summary="Confirm email verification (+10%)",
)
async def confirm_email_verification(token: str, db: DatabaseDep) -> HTMLResponse:
    """Validate the emailed token and mark the user's email verified (+10%)."""
    settings = get_settings()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await db.fetchrow(
        """
        select id, (metadata->>'expires_at')::timestamptz as expires_at
        from public.user_verifications
        where type = 'email' and metadata->>'token_hash' = $1
        """,
        token_hash,
    )
    if row is None:
        raise BadRequestError("Invalid or unknown verification link.")
    if row["expires_at"] is not None and row["expires_at"] < datetime.now(UTC):
        raise BadRequestError("This verification link has expired; request a new one.")
    await db.execute(
        """
        update public.user_verifications
           set status = 'verified', percent_awarded = $2, verified_at = now()
         where id = $1
        """,
        row["id"],
        settings.email_verification_percent,
    )
    log.info("email_verified", verification_id=str(row["id"]))
    return HTMLResponse(
        "<html><body style='font-family:sans-serif'>"
        "<h2>Email verified &#10003;</h2>"
        "<p>Your RepLiT email is confirmed (+10%). You can close this tab.</p>"
        "</body></html>"
    )