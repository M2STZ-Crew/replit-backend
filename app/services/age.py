"""Who may hold a RepLiT account: adults, 18 and over (12 November 2026).

"date of birth: don't accept 17 y/o and below". A date of birth stays
optional, but one that makes the person younger than 18 is refused, at sign-up
and on the profile, with a 400 ``underage`` that the app puts in its own words.
Ages are counted on the Philippine calendar (UTC+8, no daylight saving): a
resident who turns 18 today may sign up today, not eight hours later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from app.core.exceptions import BadRequestError

MINIMUM_AGE = 18

_MANILA = timezone(timedelta(hours=8))


class UnderageError(BadRequestError):
    """A date of birth that makes the person younger than [MINIMUM_AGE]."""

    error_code = "underage"


def today_in_manila(now: datetime | None = None) -> date:
    """Today's date in the Philippines."""
    return (now or datetime.now(UTC)).astimezone(_MANILA).date()


def age_on(born: date, today: date) -> int:
    """Whole years from ``born`` to ``today``: a birthday not yet reached this
    year does not count. Someone born on 29 February turns a year older on
    1 March in a common year."""
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years


def ensure_adult(born: date | None, *, today: date | None = None) -> None:
    """Refuse a date of birth in the future, or one under [MINIMUM_AGE].

    None passes: the date of birth is optional.
    """
    if born is None:
        return
    today = today or today_in_manila()
    if born > today:
        raise BadRequestError(
            "Your date of birth can't be in the future.",
            details={"field": "date_of_birth"},
            error_code="invalid_date_of_birth",
        )
    if age_on(born, today) < MINIMUM_AGE:
        raise UnderageError(
            f"You must be {MINIMUM_AGE} or older to use RepLiT.",
            details={"field": "date_of_birth", "minimum_age": MINIMUM_AGE},
        )
