"""Disposable Email Address (DEA) detection: burner, throwaway email addresses.

A resident's email is how they sign in, where their password reset goes, and
10% of their trust level once confirmed; a staff member's personal email is
where every password link goes; an affiliate's contact email is where the
approval goes. An address from a throwaway service (mailinator.com,
10minutemail.com, ...) stops working within the hour, so it is refused
wherever RepLiT takes an email it will rely on: signing up, the email link,
a staff member's personal email, and an affiliate's contact email
(:func:`ensure_not_disposable`, a 400 ``disposable_email``).

Not checked: signing in and resetting a password, so an account made with
such an address before v1.12.23 keeps working (it only cannot confirm the
email), and an Admin making an account by hand (POST /admin/users), which is
how test accounts are made.

The list is the community-maintained disposable-email-domains blocklist
(CC0, app/data/disposable_email_domains.txt; refresh it with
scripts/update_disposable_domains.py). A listed domain covers its subdomains
too (x.mailinator.com). The providers people really use are never refused,
whatever the list says (:data:`ALWAYS_ALLOWED`), and two settings change the
rest on Render without a deploy: DISPOSABLE_EMAIL_DOMAINS_EXTRA refuses more
domains, DISPOSABLE_EMAIL_DOMAINS_ALLOWED lifts ones the list has wrong.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import BadRequestError

LIST_PATH = Path(__file__).resolve().parents[1] / "data" / "disposable_email_domains.txt"

# The mail providers people really use, the Philippines' among them, and the
# relays that forward to one: never refused, whatever the list says.
ALWAYS_ALLOWED = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.com.ph",
        "ymail.com",
        "rocketmail.com",
        "outlook.com",
        "outlook.ph",
        "hotmail.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "gmx.com",
        "gmx.net",
        "mail.com",
        "zoho.com",
        "zohomail.com",
        "yandex.com",
        "tutanota.com",
        "tuta.io",
        "fastmail.com",
        "hey.com",
        "duck.com",
        "mozmail.com",
        "privaterelay.appleid.com",
        "replit.com",
    }
)


class DisposableEmailError(BadRequestError):
    """An address from a throwaway email service (HTTP 400)."""

    error_code = "disposable_email"


@cache
def bundled_domains() -> frozenset[str]:
    """The domains in app/data/disposable_email_domains.txt, read once."""
    lines = LIST_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def _setting_domains(value: str) -> set[str]:
    return {d.strip().lower().rstrip(".") for d in value.split(",") if d.strip()}


def email_domain(email: str) -> str:
    """The part after the last @, lowercased, without a trailing dot, and in
    its ASCII (IDNA) form when it is written in another script."""
    domain = email.strip().rpartition("@")[2].strip().rstrip(".").lower()
    try:
        return domain.encode("idna").decode("ascii")
    except UnicodeError:
        return domain


def disposable_domain(email: str) -> str | None:
    """The throwaway service ``email`` belongs to, as listed, or None.

    The domain is looked up, then each domain it sits under, never the bare
    top-level one: ``a.b.mailinator.com`` is found as ``mailinator.com``. An
    allowed domain found first ends the search.
    """
    domain = email_domain(email)
    labels = domain.split(".")
    if len(labels) < 2 or not all(labels):
        return None
    settings = get_settings()
    allowed = ALWAYS_ALLOWED | _setting_domains(settings.disposable_email_domains_allowed)
    extra = _setting_domains(settings.disposable_email_domains_extra)
    listed = bundled_domains()
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        if candidate in allowed:
            return None
        if candidate in extra or candidate in listed:
            return candidate
    return None


def is_disposable(email: str) -> bool:
    """Whether ``email`` is from a throwaway email service."""
    return disposable_domain(email) is not None


def ensure_not_disposable(
    email: str | None, *, field: str = "email", message: str | None = None
) -> None:
    """Refuse an address from a throwaway service: 400 ``disposable_email``.

    ``details`` names the request field and the service, so a client can mark
    the field and say which; an empty ``email`` passes (it is optional where
    it may be empty).
    """
    if not email:
        return
    domain = disposable_domain(email)
    if domain is None:
        return
    raise DisposableEmailError(
        message
        or f"{domain} gives out temporary email addresses, which RepLiT cannot use. "
        "Use an email you will keep, such as Gmail or Yahoo.",
        details={"field": field, "domain": domain},
    )
