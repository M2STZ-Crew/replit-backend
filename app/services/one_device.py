"""One phone per account: the newest sign-in wins (12 November 2026).

"single device only policy. if the account is opened in another device it has
a warning and a button will lead to exit". Every sign-in makes a Supabase Auth
session, and every access token names its session (the ``session_id``
claim). A request whose session is not the account's newest is refused with
a 403 ``signed_in_elsewhere``; the app answers it with the warning and Exit,
and the console with its sign-in page. Signing out on the newer phone deletes
its session, and the older one works again.

The newest session is read from ``auth.sessions`` and kept for
[_FRESH_FOR] seconds per account, so a request costs no extra query while it
is still the newest. Should the database role not be allowed to read
``auth.sessions``, the check turns itself off and says so in the log once:
an account on two phones is better than nobody signed in at all.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from app.core.exceptions import ForbiddenError
from app.core.logging import get_logger

log = get_logger(__name__)

_FRESH_FOR = 15.0
_newest: dict[UUID, tuple[str | None, float]] = {}
_unavailable = False


class SignedInElsewhereError(ForbiddenError):
    """This session is not the account's newest: it was opened on another phone."""

    error_code = "signed_in_elsewhere"


SIGNED_IN_ELSEWHERE = (
    "Your account was opened on another phone, so it has been signed out here."
)


def reset() -> None:
    """For tests: forget every account's newest session, and turn the check on."""
    global _unavailable
    _newest.clear()
    _unavailable = False


async def assert_newest_session(
    db: Any, user_id: UUID, session_id: object, *, now: float | None = None
) -> None:
    """Refuse a token whose session is not the account's newest.

    A token with no session claim (a service token, a test) passes.
    """
    global _unavailable
    if _unavailable or not isinstance(session_id, str) or not session_id:
        return
    now = time.monotonic() if now is None else now
    cached = _newest.get(user_id)
    if cached is not None and cached[0] == session_id and now - cached[1] < _FRESH_FOR:
        return
    try:
        newest = await db.fetchval(
            """
            select s.id::text from auth.sessions s
             where s.user_id = $1
             order by s.created_at desc
             limit 1
            """,
            user_id,
        )
    except Exception:
        _unavailable = True
        log.warning("one_device_check_unavailable", exc_info=True)
        return
    _newest[user_id] = (newest, now)
    if newest is None or newest == session_id:
        return
    raise SignedInElsewhereError(SIGNED_IN_ELSEWHERE, details={"reason": "newer_sign_in"})
