"""Progressive verification endpoints.

Phone OTP (+40%) through Semaphore; for a citizen it also gates the app.
Phase 4: Didit.me National ID KYC (+50%) via a hosted session, with a
poll/refresh path and an HMAC-verified webhook. Approved => +50%;
Declined / In Review => routed to the Admin manual-review queue (Section 3.2).
The app takes the manual route: ID, QR code and selfie photos for an Admin, who
runs the QR code through PSA's PhilSys Check.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse

from app.api.deps import (
    CurrentUser,
    DatabaseDep,
    DiditClientDep,
    EmailClientDep,
    SemaphoreDep,
    SessionUser,
    StorageClientDep,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AppError,
    BadRequestError,
    ExternalServiceError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.verification import (
    EmailLinkResponse,
    NationalIdStartResponse,
    PhoneCodeRequestResponse,
    PhoneVerifyCheckRequest,
    PhoneVerifyStartRequest,
    VerificationChannelStatus,
    VerificationResultResponse,
    VerificationStatusResponse,
)
from app.services.disposable_email import ensure_not_disposable
from app.services.email_layout import EmailAction, RenderedEmail, render_email
from app.services.link_page import link_page
from app.services.national_id import BUCKET, photo_paths, remove_photos
from app.services.phone_verification import check_code, request_code

log = get_logger(__name__)

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get(
    "/status",
    response_model=VerificationStatusResponse,
    summary="My progressive-verification standing, per channel",
)
async def verification_status(
    user: SessionUser, db: DatabaseDep
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
# Phone OTP (+40%) — Semaphore. For a citizen this is also the gate: the account
# cannot use the app until a number is verified, so both routes take
# SessionUser rather than CurrentUser.
# --------------------------------------------------------------------------- #
@router.post(
    "/phone/request",
    response_model=PhoneCodeRequestResponse,
    summary="Text a verification code to a Philippine mobile number",
)
async def request_phone_otp(
    payload: PhoneVerifyStartRequest,
    user: SessionUser,
    db: DatabaseDep,
    sms: SemaphoreDep,
) -> PhoneCodeRequestResponse:
    """Send a code, within the per-account cooldown and the daily caps."""
    outcome = await request_code(db, sms, user, payload.phone)
    return PhoneCodeRequestResponse(
        message=outcome.message,
        phone=outcome.phone,
        sent=outcome.sent,
        expires_in_seconds=outcome.expires_in_seconds,
        resend_after_seconds=outcome.resend_after_seconds,
    )


@router.post(
    "/phone/verify",
    response_model=VerificationResultResponse,
    summary="Verify the SMS code (+40%)",
)
async def verify_phone_otp(
    payload: PhoneVerifyCheckRequest,
    user: SessionUser,
    db: DatabaseDep,
) -> VerificationResultResponse:
    """Check the code; on a match the number is verified and the +40% awarded."""
    outcome = await check_code(db, user, payload.code)
    result = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", user.id
    )
    assert result is not None
    return VerificationResultResponse(
        verified=outcome.verified,
        verified_percent=result["verified_percent"],
        badge=str(result["badge"]),
        message=outcome.message,
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
# National ID manual upload: the route the app uses (no Didit credits needed)
# --------------------------------------------------------------------------- #
_MAX_ID_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


async def _read_validated_image(upload: UploadFile) -> bytes:
    """Validate an uploaded image (type + size); return its bytes."""
    if upload.content_type not in _ALLOWED_IMAGE_TYPES:
        raise BadRequestError("Only JPEG or PNG images are accepted.")
    content = await upload.read()
    if len(content) == 0:
        raise BadRequestError("Uploaded image is empty.")
    if len(content) > _MAX_ID_IMAGE_BYTES:
        raise BadRequestError("Image exceeds the 10 MB limit.")
    return content


@router.post(
    "/national-id/manual",
    response_model=VerificationResultResponse,
    summary="Submit National ID, its QR code and a selfie for Admin review",
)
async def submit_national_id_manual(
    user: CurrentUser,
    db: DatabaseDep,
    storage: StorageClientDep,
    id_image: Annotated[UploadFile, File(description="National ID photo (JPEG/PNG, <=10MB)")],
    selfie_image: Annotated[UploadFile, File(description="Matching selfie (JPEG/PNG, <=10MB)")],
    qr_image: Annotated[
        UploadFile | None, File(description="The ID's QR code (JPEG/PNG, <=10MB)")
    ] = None,
    philsys_consent: Annotated[
        bool, Form(description="The holder agrees to an Admin running PhilSys Check.")
    ] = False,
) -> VerificationResultResponse:
    """Store the photos privately and queue the user for Admin review.

    PSA's handbook asks for the holder's consent before PhilSys Check. The QR
    photo is optional only so that an older app is told why, not sent a 422.
    """
    if qr_image is None:
        raise BadRequestError("Update RepLiT to verify your National ID.")
    if not philsys_consent:
        raise BadRequestError("Agree to the PhilSys Check to continue.")
    uploads = (id_image, selfie_image, qr_image)
    contents = [await _read_validated_image(upload) for upload in uploads]

    paths = photo_paths(user.id)
    try:
        for path, upload, content in zip(paths.values(), uploads, contents, strict=True):
            await storage.upload(
                bucket=BUCKET,
                path=path,
                content=content,
                content_type=upload.content_type or "image/jpeg",
            )
    except ExternalServiceError:
        await remove_photos(storage, paths.values())
        raise
    await db.execute(
        """
        insert into public.user_verifications (user_id, type, status, provider, metadata)
        values ($1, 'national_id', 'manual_review', 'manual', $2::jsonb)
        on conflict (user_id, type) do update
           set status = 'manual_review', provider = 'manual',
               metadata = (public.user_verifications.metadata - 'philsys_result') || $2::jsonb,
               review_notes = null,
               submitted_at = now(), verified_at = null
        """,
        user.id,
        json.dumps({**paths, "philsys_consent_at": datetime.now(UTC).isoformat()}),
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
# Email verification (+10%) — Brevo link-based. Since app 1.12.29 it is the last
# step of a resident's sign-up, in place of a texted code while SMS is
# undecided: the app asks for the link the moment the account exists.
# --------------------------------------------------------------------------- #
EMAIL_LINK_FOR = timedelta(hours=24)


class EmailLinkCooldownError(AppError):
    """Asked for another link too soon (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "email_link_cooldown"


class EmailLinkLimitError(AppError):
    """The day's links for this account are spent (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "email_link_daily_limit"


def _recent_sends(raw: str | None, now: datetime) -> list[datetime]:
    """When the links of the last 24 hours went out, oldest first."""
    try:
        stamps = json.loads(raw or "[]")
    except ValueError:
        return []
    day_ago = now - timedelta(hours=24)
    sends: list[datetime] = []
    for stamp in stamps if isinstance(stamps, list) else []:
        try:
            moment = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        if moment > day_ago:
            sends.append(moment)
    return sorted(sends)


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, int((moment - now).total_seconds()) + 1)


def _verification_email(full_name: str | None, link: str) -> RenderedEmail:
    """The verify-your-email message (HTML and plain text). Until v1.12.19 it
    was HTML alone, with the name unescaped; render_email escapes it."""
    return render_email(
        preheader="Confirm this email address for your RepLiT account. The link "
        "works for 24 hours.",
        heading="Verify your email address",
        greeting=f"Hello {full_name}," if full_name else "Hello,",
        paragraphs=[
            "Please confirm that this is the email address for your RepLiT account.",
        ],
        action=EmailAction("Verify my email", link),
        facts=[
            "This link expires 24 hours after this email was sent. After that, "
            "request a new one from the RepLiT app.",
        ],
        notice="If you did not ask to verify this address, you can ignore this email: "
        "nothing changes until the link is opened.",
        reason="You are receiving this email because email verification was "
        "requested for a RepLiT account that uses this address.",
    )


@router.post(
    "/email/request",
    response_model=EmailLinkResponse,
    summary="Send an email verification link (+10%)",
)
async def request_email_verification(
    user: CurrentUser, db: DatabaseDep, email: EmailClientDep
) -> EmailLinkResponse:
    """Email a one-time link that confirms the user's address.

    Runs under an advisory lock keyed on the account, so two taps cannot both
    pass the wait between links. The email is sent inside the transaction: if
    Brevo refuses, nothing is recorded, so a failed send spends neither the
    wait nor the day's allowance. An address already confirmed gets no email
    and stays confirmed; until v1.12.22 asking again set it back to pending.
    """
    settings = get_settings()
    if not user.email:
        raise BadRequestError("Your account has no email address to verify.")
    # An account made with a burner address before v1.12.23 keeps working, but
    # a throwaway inbox earns no trust.
    ensure_not_disposable(
        user.email,
        message="Your email is from a temporary email service, so it cannot be confirmed.",
    )
    cooldown = timedelta(seconds=settings.email_link_resend_cooldown_seconds)
    now = datetime.now(UTC)
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"email-link:{user.id}",
        )
        row = await conn.fetchrow(
            """
            select status::text as status,
                   coalesce(metadata->'sends', '[]'::jsonb)::text as sends
              from public.user_verifications
             where user_id = $1 and type = 'email'
            """,
            user.id,
        )
        if row is not None and row["status"] == "verified":
            return EmailLinkResponse(
                message="Your email is already confirmed.",
                email=user.email,
                sent=False,
                expires_in_seconds=0,
                resend_after_seconds=0,
            )
        sends = _recent_sends(row["sends"] if row is not None else None, now)
        if sends and now - sends[-1] < cooldown:
            wait = _seconds_until(sends[-1] + cooldown, now)
            raise EmailLinkCooldownError(
                f"We just sent a link. You can ask for another in {wait} seconds.",
                details={"retry_after_seconds": wait},
            )
        if len(sends) >= settings.email_link_daily_limit_per_user:
            wait = _seconds_until(sends[0] + timedelta(hours=24), now)
            raise EmailLinkLimitError(
                "That is all the links we can send today. Use the newest email we "
                "sent, or ask for another tomorrow.",
                details={"retry_after_seconds": wait},
            )
        token = secrets.token_urlsafe(32)
        pending = {
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": (now + EMAIL_LINK_FOR).isoformat(),
            "sends": [moment.isoformat() for moment in [*sends, now]],
        }
        await conn.execute(
            """
            insert into public.user_verifications (user_id, type, status, provider, metadata)
            values ($1, 'email', 'pending', 'brevo', $2::jsonb)
            on conflict (user_id, type) do update
               set status = 'pending', provider = 'brevo',
                   metadata = public.user_verifications.metadata || $2::jsonb,
                   submitted_at = now(), verified_at = null
            """,
            user.id,
            json.dumps(pending),
        )
        link = f"{settings.public_base_url.rstrip('/')}/verification/email/confirm?token={token}"
        message = _verification_email(user.full_name, link)
        await email.send(
            to=user.email,
            subject="Verify your RepLiT email",
            html=message.html,
            text=message.text,
        )
    log.info("email_verification_requested", user_id=str(user.id))
    return EmailLinkResponse(
        message="Verification email sent. Check your inbox.",
        email=user.email,
        sent=True,
        expires_in_seconds=int(EMAIL_LINK_FOR.total_seconds()),
        resend_after_seconds=settings.email_link_resend_cooldown_seconds,
    )


# Where a resident sends a new link from, in the app.
_SEND_A_NEW_ONE = "open the RepLiT app and send a new one: Profile, then Verify next to your email."


@router.get(
    "/email/confirm",
    response_class=HTMLResponse,
    summary="Confirm email verification (+10%)",
)
async def confirm_email_verification(
    db: DatabaseDep, token: str = Query(default="", max_length=512)
) -> HTMLResponse:
    """The emailed link: the address is confirmed (+10%).

    It opens in a phone's browser, or Gmail's, so every outcome is a page that
    says what to do next, never an error in JSON. Opening it again says
    confirmed again and changes nothing.
    """
    settings = get_settings()
    row = None
    if token:
        row = await db.fetchrow(
            """
            select id, status::text as status,
                   (metadata->>'expires_at')::timestamptz as expires_at
              from public.user_verifications
             where type = 'email' and metadata->>'token_hash' = $1
            """,
            hashlib.sha256(token.encode()).hexdigest(),
        )
    if row is None:
        return link_page(
            "Link not valid",
            "This link does not work",
            "Each new link replaces the one before it. Use the link in the newest "
            "email from RepLiT, or " + _SEND_A_NEW_ONE,
            status_code=400,
        )
    if row["status"] == "verified":
        return link_page(
            "Email confirmed",
            "Your email is confirmed",
            "Go back to the RepLiT app to continue. You can close this page.",
        )
    if row["expires_at"] is not None and row["expires_at"] < datetime.now(UTC):
        return link_page(
            "Link expired",
            "This link has expired",
            "Links work for 24 hours. To confirm your email, " + _SEND_A_NEW_ONE,
            status_code=400,
        )
    await db.execute(
        """
        update public.user_verifications
           set status = 'verified', percent_awarded = $2, verified_at = now()
         where id = $1 and status <> 'verified'
        """,
        row["id"],
        settings.email_verification_percent,
    )
    log.info("email_verified", verification_id=str(row["id"]))
    return link_page(
        "Email confirmed",
        "Your email is confirmed",
        f"Thank you. Your trust level is up {settings.email_verification_percent}%. "
        "Go back to the RepLiT app to continue. You can close this page.",
    )