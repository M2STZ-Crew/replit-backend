"""Staff accounts: the sign-in address a new coordinator or responder gets.

The account directory's rule (the 6 November list): the first name's initial
and the full surname, then a dot, then the agency and the role, at the RepLiT
domain —

    Odyssey Bryan, a Fire Volunteer coordinator  ->  obryan.fircor@replit.com
    Juan Dela Cruz, a Fire Volunteer responder   ->  jdelacruz.firres@replit.com

The agency part: ``fir`` Fire Volunteer, ``bfp`` BFP, ``pol`` police, ``med``
medical, ``bar`` barangay. The role part: ``cor`` coordinator, ``res``
responder. Until then responders' addresses put the role first
(jdelacruz.resfir), and coordinators signed in with their own email; those
accounts keep what they have.

@replit.com has no mailboxes, so what a password needs goes to the person's own
email instead (users.personal_email, app/services/staff_links.py).

When the address is taken — two people in the same agency and role with the
same initial and surname — the first keeps it and each later one gets the next
number straight after the surname: jdelacruz1.firres, jdelacruz2.firres, and so
on.

Pure functions, so the rule is tested without a database.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Iterable
from typing import Literal

DOMAIN = "replit.com"

# The agency part of the agency-and-role suffix (account directory).
AGENCY_CODES: dict[str, str] = {
    "fire_volunteer": "fir",
    "bfp": "bfp",
    "police": "pol",
    "medical": "med",
    "barangay": "bar",
}

StaffRole = Literal["coordinator", "responder"]

# The role part, after the agency.
ROLE_CODES: dict[str, str] = {"coordinator": "cor", "responder": "res"}


class InvalidNameError(ValueError):
    """A name that leaves nothing to build an address from."""


def _letters(text: str) -> str:
    """Lower-case ASCII letters only: 'Peña' -> 'pena', 'Dela Cruz' -> 'delacruz'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", ascii_only.lower())


def local_base(first_name: str, last_name: str) -> str:
    """The first initial and the full surname: 'jdelacruz'."""
    first = _letters(first_name)
    last = _letters(last_name)
    if not first or not last:
        raise InvalidNameError("Enter a first name and a surname with letters in them.")
    return f"{first[0]}{last}"


def staff_suffix(agency: str, role: StaffRole) -> str:
    """'fircor' for a Fire Volunteer coordinator, 'polres' for a police responder."""
    code = AGENCY_CODES.get(agency)
    if code is None:
        raise ValueError(f"No staff accounts for agency {agency!r}.")
    return f"{code}{ROLE_CODES[role]}"


def staff_email(
    first_name: str,
    last_name: str,
    agency: str,
    role: StaffRole,
    taken: Iterable[str],
    *,
    domain: str = DOMAIN,
) -> str:
    """The next free address for this person, given the addresses ``taken``.

    No one with this initial, surname, agency and role yet: the plain address.
    Otherwise the number after the highest one in use (the plain address
    counting as 0), so the numbers run on in order and a removed account's
    number is not handed to someone else.
    """
    base = local_base(first_name, last_name)
    suffix = staff_suffix(agency, role)
    pattern = re.compile(
        rf"^{re.escape(base)}(\d*)\.{re.escape(suffix)}@{re.escape(domain)}$"
    )
    numbers: list[int] = []
    for email in taken:
        match = pattern.match(email.strip().lower())
        if match:
            numbers.append(int(match.group(1) or 0))
    number = "" if not numbers else str(max(numbers) + 1)
    return f"{base}{number}.{suffix}@{domain}"


def staff_like_pattern(
    first_name: str,
    last_name: str,
    agency: str,
    role: StaffRole,
    *,
    domain: str = DOMAIN,
) -> str:
    """A SQL LIKE pattern for every address this person's could collide with."""
    base = local_base(first_name, last_name)
    return f"{base}%.{staff_suffix(agency, role)}@{domain}"


def is_staff_address(email: str | None) -> bool:
    """An address at the RepLiT domain: a sign-in with no mailbox behind it."""
    return bool(email) and str(email).strip().lower().endswith(f"@{DOMAIN}")


# The responder forms, as routes/team.py uses them.
def responder_suffix(agency: str) -> str:
    """'firres' for a Fire Volunteer responder, 'polres' for a police one, ..."""
    return staff_suffix(agency, "responder")


def responder_email(
    first_name: str,
    last_name: str,
    agency: str,
    taken: Iterable[str],
    *,
    domain: str = DOMAIN,
) -> str:
    """The next free responder address: see :func:`staff_email`."""
    return staff_email(first_name, last_name, agency, "responder", taken, domain=domain)


def like_pattern(first_name: str, last_name: str, agency: str, *, domain: str = DOMAIN) -> str:
    """A SQL LIKE pattern for a responder's address: see :func:`staff_like_pattern`."""
    return staff_like_pattern(first_name, last_name, agency, "responder", domain=domain)


# No 0/O, 1/l/I: the password is read off one phone and typed into another.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def temporary_password() -> str:
    """A strong password to hand over in person: 'Kq7m-x3Rt-9pWa'.

    Three groups of four from an alphabet without look-alike characters, with
    at least one upper-case letter, one lower-case letter and one digit.
    """
    while True:
        chars = [secrets.choice(_ALPHABET) for _ in range(12)]
        if (
            any(c.isupper() for c in chars)
            and any(c.islower() for c in chars)
            and any(c.isdigit() for c in chars)
        ):
            groups = ["".join(chars[i : i + 4]) for i in range(0, 12, 4)]
            return "-".join(groups)
