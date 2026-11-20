"""v1.12.47 (20 Nov 2026, "fix the pagination bar in admin"; answered "One
pager everywhere"): the console reads a list whole and pages it itself, so a
search covers every row rather than one page. It asks for the latest 200
post-incident reports (201, to know whether there are more) and the latest
500 audit entries, which it groups by incident."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.main import app
from app.schemas.auth import AuthenticatedUser


class _DB:
    """Records each list query's parameters; every list is empty."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.calls.append((sql, args))
        return []


@pytest.fixture
def db() -> Iterator[_DB]:
    fake = _DB()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid4(), role="admin", full_name="System Administrator",
    )
    app.dependency_overrides[get_database] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_the_console_reads_up_to_500_reports_at_once(db: _DB) -> None:
    with TestClient(app) as client:
        assert client.get("/post-incident-reports?limit=201").status_code == 200
        assert db.calls[-1][1][-2:] == (201, 0)
        assert client.get("/post-incident-reports?limit=500").status_code == 200
        assert client.get("/post-incident-reports?limit=501").status_code == 422


def test_the_console_reads_the_latest_500_audit_entries(db: _DB) -> None:
    with TestClient(app) as client:
        assert client.get("/audit-logs?limit=500").status_code == 200
        assert db.calls[-1][1][-2:] == (500, 0)
        assert client.get("/audit-logs?limit=501").status_code == 422
