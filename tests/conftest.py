"""The tests have no database.

``with TestClient(app)`` runs the app's startup, which opens the pool from .env,
and the audit middleware writes through that pool, past every dependency override.
A passing test left 8 rows in the live audit_logs that way (31 Oct 2026). This runs
before anything imports the settings, and a set variable beats .env.
"""

import os

os.environ["DATABASE_URL"] = ""
# No DNS from the tests: a sign-up's email check (v1.12.34) is asked of a
# fake resolver where a test wants it (tests/test_v1_12_34.py).
os.environ["EMAIL_DELIVERABILITY_CHECK"] = "false"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _forget_wrong_passwords() -> Iterator[None]:
    """Each test starts with no wrong passwords counted (v1.12.36): the count is
    kept in memory for the whole run, so one test's tries would lock another's."""
    from app.services import password_attempts

    password_attempts.reset()
    yield
    password_attempts.reset()
