"""Phone verification by SMS code, sent through Semaphore.

Verifying a mobile number earns the phone channel's +40% (Section 2.1), and for
a citizen it is also the gate: the account cannot use the app until a number is
verified. Twilio Verify used to generate and check the codes; Semaphore only
delivers them, so this module owns the rest.

How a code is held. Never in plain text: only an HMAC of (account, number,
code) under a key derived from the server's JWT secret, in the phone row of
user_verifications. A code is bound to the account and the number it was sent
to, expires after a few minutes, and is thrown away after a few wrong guesses —
a six-digit code has only a million values, so the attempt cap is what makes
guessing hopeless rather than slow.

How sending is limited. Each text costs Semaphore credit and nothing upstream
rate-limits the OTP route, so three limits apply before anything is sent: a
cooldown per account, a daily cap per account, and a daily cap per number
counted across every account, so creating accounts does not buy more texts to
someone else's phone. phone_otp_sends is the ledger all three read.

How a number is claimed. One verified account per number, checked here with a
readable message and guaranteed by a partial unique index underneath.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from fastapi import status

from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError, ConflictError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.semaphore_sms import SemaphoreClient, mask_number
from app.schemas.auth import AuthenticatedUser

log = get_logger(__name__)

_MESSAGE = (
    "RepLiT: your verification code is {otp}. It expires in {minutes} minutes. "
    "Never share this code with anyone."
)

# Philippine mobile numbers: +63 9XX XXX XXXX. Semaphore delivers to PH networks
# only, so a number outside this shape could never receive the code anyway.
_PH_MOBILE = re.compile(r"^\+639\d{9}$")


class PhoneCodeCooldownError(AppError):
    """Asked for another code too soon (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "phone_code_cooldown"


class PhoneCodeLimitError(AppError):
    """Daily allowance of codes spent, for this account or this number (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "phone_code_daily_limit"


class PhoneNumberTakenError(ConflictError):
    """Another account already verified this number (HTTP 409)."""

    error_code = "phone_number_taken"


@dataclass(frozen=True)
class CodeRequestOutcome:
    """What asking for a code came to."""

    message: str
    phone: str
    sent: bool
    expires_in_seconds: int
    resend_after_seconds: int


@dataclass(frozen=True)
class CodeCheckOutcome:
    """What submitting a code came to."""

    verified: bool
    message: str
    attempts_left: int | None = None


def normalize_ph_mobile(raw: str) -> str:
    """Return a Philippine mobile number as E.164 (+639XXXXXXXXX), or raise 400.

    Accepts how people actually type one: 0917 123 4567, 09171234567,
    +63 917-123-4567, 639171234567 and 9171234567.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("63") and len(digits) == 12:
        candidate = f"+{digits}"
    elif digits.startswith("09") and len(digits) == 11:
        candidate = f"+63{digits[1:]}"
    elif digits.startswith("9") and len(digits) == 10:
        candidate = f"+63{digits}"
    else:
        candidate = ""
    if not _PH_MOBILE.match(candidate):
        raise BadRequestError(
            "Enter a Philippine mobile number, like 0917 123 4567.",
            details={"field": "phone"},
        )
    return candidate


def to_semaphore_number(e164: str) -> str:
    """+639XXXXXXXXX -> 639XXXXXXXXX, the form Semaphore's documentation uses."""
    return e164.lstrip("+")


def _hmac_key() -> bytes:
    """A key for code MACs, derived from — and kept separate from — the JWT secret."""
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is required to protect phone codes.")
    return hmac.new(secret.encode(), b"replit/phone-otp/v1", hashlib.sha256).digest()


def code_mac(user_id: object, phone: str, code: str) -> str:
    """Bind a code to its account and number, so a stored MAC proves nothing alone."""
    message = f"{user_id}|{phone}|{code}".encode()
    return hmac.new(_hmac_key(), message, hashlib.sha256).hexdigest()


def _generate_code(length: int) -> str:
    return f"{secrets.randbelow(10**length):0{length}d}"


def _metadata(value: Any) -> dict[str, Any]:
    """asyncpg returns jsonb as text here; normalise to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, int((moment - now).total_seconds()) + 1)


async def request_code(
    db: Database, sms: SemaphoreClient, user: AuthenticatedUser, raw_phone: str
) -> CodeRequestOutcome:
    """Text a fresh code to ``raw_phone`` for ``user``, within every limit.

    Runs under an advisory lock keyed on the account, so two taps on Resend
    cannot both pass the cooldown. The SMS is sent inside the transaction: if
    Semaphore refuses, nothing is recorded, so a failed send neither spends the
    cooldown nor counts toward a daily cap.
    """
    settings = get_settings()
    phone = normalize_ph_mobile(raw_phone)
    ttl = settings.phone_otp_ttl_seconds
    cooldown = timedelta(seconds=settings.phone_otp_resend_cooldown_seconds)

    if user.phone_verified and user.phone == phone:
        return CodeRequestOutcome(
            message="This number is already verified on your account.",
            phone=phone,
            sent=False,
            expires_in_seconds=0,
            resend_after_seconds=0,
        )

    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"phone-otp:{user.id}",
        )
        taken = await conn.fetchval(
            "select exists (select 1 from public.users "
            "where phone = $1 and phone_verified and id <> $2)",
            phone,
            user.id,
        )
        if taken:
            raise PhoneNumberTakenError(
                "This number is already verified on another RepLiT account. Use a "
                "different number, or sign in to that account."
            )

        last_sent = await conn.fetchval(
            "select max(sent_at) from public.phone_otp_sends where user_id = $1",
            user.id,
        )
        if last_sent is not None and now - last_sent < cooldown:
            wait = _seconds_until(last_sent + cooldown, now)
            raise PhoneCodeCooldownError(
                f"We just sent a code. You can ask for another in {wait} seconds.",
                details={"retry_after_seconds": wait},
            )

        by_user = await conn.fetch(
            "select sent_at from public.phone_otp_sends "
            "where user_id = $1 and sent_at > $2 order by sent_at",
            user.id,
            day_ago,
        )
        if len(by_user) >= settings.phone_otp_daily_limit_per_user:
            wait = _seconds_until(by_user[0]["sent_at"] + timedelta(hours=24), now)
            raise PhoneCodeLimitError(
                "That is the most codes we can send to your account today. Try again "
                "tomorrow.",
                details={"retry_after_seconds": wait, "scope": "account"},
            )

        by_number = await conn.fetch(
            "select sent_at from public.phone_otp_sends "
            "where phone = $1 and sent_at > $2 order by sent_at",
            phone,
            day_ago,
        )
        if len(by_number) >= settings.phone_otp_daily_limit_per_number:
            wait = _seconds_until(by_number[0]["sent_at"] + timedelta(hours=24), now)
            raise PhoneCodeLimitError(
                "That number has received the most codes we can send today. Try again "
                "tomorrow.",
                details={"retry_after_seconds": wait, "scope": "number"},
            )

        code = _generate_code(settings.phone_otp_length)
        sent = await sms.send_otp(
            number=to_semaphore_number(phone),
            code=code,
            message=_MESSAGE.replace("{minutes}", str(max(1, ttl // 60))),
        )

        await conn.execute(
            "insert into public.phone_otp_sends (user_id, phone, provider_message_id) "
            "values ($1, $2, $3)",
            user.id,
            phone,
            sent.message_id,
        )
        pending = {
            "phone": phone,
            "code_mac": code_mac(user.id, phone, code),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "attempts": 0,
        }
        await conn.execute(
            """
            insert into public.user_verifications
                (user_id, type, status, provider, provider_reference, metadata)
            values ($1, 'phone', 'pending', 'semaphore', $2, $3::jsonb)
            on conflict (user_id, type) do update
               set status = case
                       when public.user_verifications.status = 'verified'
                       then public.user_verifications.status
                       else 'pending'
                   end,
                   provider = 'semaphore',
                   provider_reference = $2,
                   metadata = public.user_verifications.metadata || $3::jsonb,
                   submitted_at = now()
            """,
            user.id,
            sent.message_id,
            json.dumps(pending),
        )

    log.info("phone_code_requested", user_id=str(user.id), number=mask_number(phone))
    return CodeRequestOutcome(
        message=f"We texted a code to {phone}. It expires in {max(1, ttl // 60)} minutes.",
        phone=phone,
        sent=True,
        expires_in_seconds=ttl,
        resend_after_seconds=settings.phone_otp_resend_cooldown_seconds,
    )


async def check_code(db: Database, user: AuthenticatedUser, code: str) -> CodeCheckOutcome:
    """Check ``code``; on a match, verify the number and award the phone channel.

    Wrong guesses are counted and committed *before* the refusal is raised —
    raising inside the transaction would roll the count back and make the
    attempt cap decorative. At the cap, or past expiry, the code is discarded.
    """
    settings = get_settings()
    submitted = re.sub(r"\D", "", code or "")
    now = datetime.now(UTC)

    refusal: AppError | None = None
    outcome: CodeCheckOutcome | None = None
    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "select id, status::text as status, metadata from public.user_verifications "
            "where user_id = $1 and type = 'phone' for update",
            user.id,
        )
        meta = _metadata(row["metadata"]) if row else {}
        phone = meta.get("phone")
        stored_mac = meta.get("code_mac")

        if row is None or not stored_mac or not isinstance(phone, str):
            if user.phone_verified:
                return CodeCheckOutcome(verified=True, message="Your number is already verified.")
            raise BadRequestError("Ask for a code first.")

        expires_raw = meta.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(str(expires_raw))
        except ValueError:
            expires_at = now
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        attempts = int(meta.get("attempts") or 0)
        cap = settings.phone_otp_max_attempts

        if expires_at <= now:
            await _discard_code(conn, row["id"])
            refusal = BadRequestError(
                "This code has expired. Ask for a new one.",
                details={"reason": "expired"},
            )
        elif attempts >= cap:
            await _discard_code(conn, row["id"])
            refusal = BadRequestError(
                "Too many wrong codes. Ask for a new one.",
                details={"reason": "too_many_attempts"},
            )
        elif not hmac.compare_digest(stored_mac, code_mac(user.id, phone, submitted)):
            attempts += 1
            left = cap - attempts
            if left <= 0:
                await _discard_code(conn, row["id"])
                refusal = BadRequestError(
                    "That code is wrong, and it was the last try. Ask for a new code.",
                    details={"reason": "too_many_attempts", "attempts_left": 0},
                )
            else:
                await conn.execute(
                    "update public.user_verifications "
                    "set metadata = metadata || jsonb_build_object('attempts', $2::int) "
                    "where id = $1",
                    row["id"],
                    attempts,
                )
                refusal = BadRequestError(
                    f"That code is wrong. {left} {'try' if left == 1 else 'tries'} left.",
                    details={"reason": "wrong_code", "attempts_left": left},
                )
        else:
            taken = await conn.fetchval(
                "select exists (select 1 from public.users "
                "where phone = $1 and phone_verified and id <> $2)",
                phone,
                user.id,
            )
            if taken:
                await _discard_code(conn, row["id"])
                refusal = PhoneNumberTakenError(
                    "This number was verified on another RepLiT account in the meantime."
                )
            else:
                try:
                    # A savepoint: if the unique index fires, Postgres aborts the
                    # enclosing transaction, and catching the exception would not
                    # un-abort it. The nested block rolls back to here instead.
                    async with conn.transaction():
                        # The number first, then the status: the status change is
                        # what sets users.phone_verified (via the recompute
                        # trigger), and the unique index then covers a number that
                        # is already in place.
                        await conn.execute(
                            "update public.users set phone = $2 where id = $1", user.id, phone
                        )
                        await conn.execute(
                            """
                            update public.user_verifications
                               set status = 'verified', percent_awarded = $2,
                                   verified_at = now(),
                                   metadata = (metadata - 'code_mac' - 'expires_at' - 'attempts')
                                              || jsonb_build_object('verified_phone', $3::text)
                             where id = $1
                            """,
                            row["id"],
                            settings.phone_verification_percent,
                            phone,
                        )
                except asyncpg.UniqueViolationError:
                    refusal = PhoneNumberTakenError(
                        "This number is already verified on another RepLiT account."
                    )
                else:
                    outcome = CodeCheckOutcome(verified=True, message="Your number is verified.")

    if refusal is not None:
        log.info(
            "phone_code_refused",
            user_id=str(user.id),
            reason=(refusal.details or {}).get("reason", refusal.error_code),
        )
        raise refusal
    assert outcome is not None
    log.info("phone_verified", user_id=str(user.id))
    return outcome


async def _discard_code(conn: asyncpg.Connection, verification_id: object) -> None:
    await conn.execute(
        "update public.user_verifications "
        "set metadata = metadata - 'code_mac' - 'expires_at' - 'attempts' where id = $1",
        verification_id,
    )
