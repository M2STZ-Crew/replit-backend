"""Can this address receive mail? Asked of its domain's DNS at sign-up (v1.12.34).

QA on 15 Nov 2026 (D-02): an address made up on the spot made an account.
Its format was right, but no mail could ever reach it, so it could never be
confirmed or have its password reset. Now the domain must exist and take mail:
an MX record, or failing that an address record, as mail servers accept.

A lookup that is slow or fails is not the person's fault, so the address is
then let through, as before. An address at a real domain that no one reads
still passes; confirming the email (+10%) is what proves it.

EMAIL_DELIVERABILITY_CHECK=false turns the lookup off (the tests do).
"""

from __future__ import annotations

import asyncio

import dns.resolver
from email_validator import EmailNotValidError, EmailUndeliverableError, validate_email

from app.core.config import get_settings
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger

log = get_logger(__name__)

# Each lookup, and all of them together: a sign-up must not wait on a slow DNS.
LOOKUP_SECONDS = 4.0

UNDELIVERABLE_MESSAGE = "No email can reach this address. Check it for typos, or use another one."


def _check(email: str) -> None:
    """Raise EmailUndeliverableError when the domain cannot take mail."""
    resolver = dns.resolver.Resolver()
    resolver.timeout = LOOKUP_SECONDS
    resolver.lifetime = LOOKUP_SECONDS
    validate_email(email, check_deliverability=True, dns_resolver=resolver)


async def ensure_deliverable(email: str) -> None:
    """Refuse (400 ``undeliverable_email``) an address whose domain takes no mail."""
    if not get_settings().email_deliverability_check:
        return
    try:
        await asyncio.to_thread(_check, email)
    except EmailUndeliverableError as exc:
        log.info("signup_undeliverable_email")
        raise BadRequestError(
            UNDELIVERABLE_MESSAGE,
            error_code="undeliverable_email",
            details={"field": "email"},
        ) from exc
    except EmailNotValidError:
        # The format is the request's own check (EmailStr); it passed that.
        return
    except Exception:  # noqa: BLE001 — no network, DNS down: let it through
        log.warning("signup_email_deliverability_unknown")
