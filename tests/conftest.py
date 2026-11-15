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
