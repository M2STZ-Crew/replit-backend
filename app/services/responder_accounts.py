"""Responder accounts: the address a coordinator's new responder gets.

The account directory's rule: the first name's initial and the full surname,
then a dot, then the role and agency, at the RepLiT domain —

    Juan Dela Cruz, a Fire Volunteer responder  ->  jdelacruz.resfir@replit.com

The role part is ``res`` (responder) followed by the agency: ``fir`` Fire
Volunteer, ``bfp`` BFP, ``pol`` police, ``med`` medical, ``bar`` barangay.

When the address is taken — two people in the same role with the same initial
and surname — the first keeps it and each later one gets the next number
straight after the surname: jdelacruz1.resfir, jdelacruz2.resfir, and so on.

Pure functions, so the rule is tested without a database.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Iterable

DOMAIN = "replit.com"

# The agency part of the role-and-agency suffix (account directory).
AGENCY_CODES: dict[str, str] = {
    "fire_volunteer": "fir",
    "bfp": "bfp",
    "police": "pol",
    "medical": "med",
    "barangay": "bar",
}

RESPONDER_ROLE_CODE = "res"


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


def responder_suffix(agency: str) -> str:
    """'resfir' for a Fire Volunteer responder, 'respol' for a police one, ..."""
    code = AGENCY_CODES.get(agency)
    if code is None:
        raise ValueError(f"No responder accounts for agency {agency!r}.")
    return f"{RESPONDER_ROLE_CODE}{code}"


def responder_email(
    first_name: str,
    last_name: str,
    agency: str,
    taken: Iterable[str],
    *,
    domain: str = DOMAIN,
) -> str:
    """The next free address for this person, given the addresses ``taken``.

    No one with this initial, surname and role yet: the plain address. Otherwise
    the number after the highest one in use (the plain address counting as 0),
    so the numbers run on in order and a removed account's number is not handed
    to someone else.
    """
    base = local_base(first_name, last_name)
    suffix = responder_suffix(agency)
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


def like_pattern(first_name: str, last_name: str, agency: str, *, domain: str = DOMAIN) -> str:
    """A SQL LIKE pattern for every address this person's could collide with."""
    base = local_base(first_name, last_name)
    return f"{base}%.{responder_suffix(agency)}@{domain}"


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
