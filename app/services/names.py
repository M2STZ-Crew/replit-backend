"""A person's name: letters, with the marks names use (v1.12.34).

QA on 15 Nov 2026 (Z-10): a name could be typed with emoji, and with digits
too. A name is "as on your ID", and staff read it on every report. Now it is
letters (ñ and accents included), with spaces, periods, apostrophes and
hyphens between them: "Ma. Luisa", "O'Neil", "Anne-Marie", "Juan Dela Cruz Jr."
Report details and notes keep accepting anything.
"""

from __future__ import annotations

import re
import unicodedata

from app.core.exceptions import BadRequestError

MAX_LENGTH = 200

# A word of letters ([^\W\d_]: a letter in any script), then more words joined
# by spaces, periods, apostrophes or hyphens; a period may end it ("Jr.").
_NAME = re.compile(r"[^\W\d_]+(?:[ .'’-]+[^\W\d_]+)*\.?")

INVALID_NAME_MESSAGE = (
    "Use letters for your name. Spaces, periods, apostrophes and hyphens are "
    "fine; numbers and emoji are not."
)


def clean_name(raw: str | None) -> str | None:
    """The name as stored: composed accents, single spaces, no ends; None if empty."""
    if raw is None:
        return None
    name = " ".join(unicodedata.normalize("NFC", raw).split())
    return name or None


def is_valid_name(name: str) -> bool:
    return len(name) <= MAX_LENGTH and _NAME.fullmatch(name) is not None


def ensure_valid_name(raw: str | None) -> str | None:
    """The cleaned name, or a 400 ``invalid_name``. None stays None."""
    name = clean_name(raw)
    if name is None:
        return None
    if not is_valid_name(name):
        raise BadRequestError(
            INVALID_NAME_MESSAGE, error_code="invalid_name", details={"field": "full_name"}
        )
    return name
