"""A limit on wrong passwords per account (v1.12.36).

Every password check here signs in to Supabase from this one server, so
Supabase's own limit, per IP address, is shared by everyone, and nothing
stopped one person from guessing at one account (QA audit, 16 November 2026).

Five wrong passwords for the same account within 15 minutes, and its password
is not checked again, here or at Supabase, until the first of those five is
15 minutes old: a 429 ``too_many_attempts`` that says how long to wait. Signing
in with the right password, or setting a new one from a reset link, clears the
count. Sign-in, the password change, and deleting or restoring an account all
share the one count.

The count is the account's email, lower-cased, so an account's email and its
verified mobile number share it. A number no account verified is counted as
itself, so it locks the same way and still says nothing about which numbers are
registered.

Kept in memory: the server runs one worker (Dockerfile ``--workers 1``), and a
restart only forgets a few minutes of counts. No table, no migration.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import status

from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_WRONG = 5
WINDOW_SECONDS = 15 * 60
# A sweep of expired counts once this many accounts are being counted, so a
# stream of made-up emails cannot grow the table without end.
_SWEEP_AT = 10_000

_clock: Callable[[], float] = time.monotonic
_wrong: dict[str, deque[float]] = {}


class TooManyWrongPasswordsError(AppError):
    """Too many wrong passwords for one account just now (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "too_many_attempts"


def _key(account: str) -> str:
    return account.strip().lower()


def _recent(key: str, now: float) -> deque[float]:
    """The account's wrong passwords still inside the window, oldest first."""
    tries = _wrong.get(key)
    if tries is None:
        return deque(maxlen=MAX_WRONG)
    while tries and now - tries[0] >= WINDOW_SECONDS:
        tries.popleft()
    if not tries:
        del _wrong[key]
    return tries


def check(account: str) -> None:
    """Raise a 429 ``too_many_attempts`` while ``account`` has to wait."""
    now = _clock()
    tries = _recent(_key(account), now)
    if len(tries) < MAX_WRONG:
        return
    wait = max(1, math.ceil(WINDOW_SECONDS - (now - tries[0])))
    minutes = max(1, math.ceil(wait / 60))
    log.info("password_attempts_locked", retry_after_seconds=wait)
    raise TooManyWrongPasswordsError(
        f"Too many wrong passwords for this account. Wait {minutes} "
        f"minute{'' if minutes == 1 else 's'}, then try again, or reset your password.",
        details={"retry_after_seconds": wait},
    )


def failed(account: str) -> None:
    """Count one wrong password for ``account``."""
    now = _clock()
    key = _key(account)
    tries = _recent(key, now)
    tries.append(now)
    _wrong[key] = tries
    if len(_wrong) > _SWEEP_AT:
        for other in list(_wrong):
            _recent(other, now)


def succeeded(account: str) -> None:
    """The right password (or a new one from a reset link): start again."""
    _wrong.pop(_key(account), None)


def reset() -> None:
    """Forget every count (tests)."""
    _wrong.clear()
