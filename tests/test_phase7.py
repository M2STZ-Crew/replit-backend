"""Phase 7 (area clustering) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.clustering import _designation
from app.services.geo import haversine_m
from app.services.incident import (
    TERMINAL_STATUSES,
    UNVERSIONABLE_STATUSES,
    active_area_sql,
    versionable_area_sql,
)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def test_designation_versions() -> None:
    """Designations: 'Area N' for v1, 'Area N.V' for later versions."""
    assert _designation(1, 1) == "Area 1"
    assert _designation(3, 2) == "Area 3.2"
    assert _designation(5, 4) == "Area 5.4"


def test_haversine_known_distance() -> None:
    """~0.0036 deg latitude is ~400 m (matches the overlap test geometry)."""
    assert 380 < haversine_m(14.6, 121.0, 14.6036, 121.0) < 420


# --------------------------------------------------------------------------- #
# Active-feed predicate (shared by clustering, the worker, and both route modules)
# --------------------------------------------------------------------------- #
def test_active_area_sql_excludes_every_terminal_status() -> None:
    """All three terminal statuses drop out of the live feed — merged included."""
    predicate = active_area_sql()
    assert set(TERMINAL_STATUSES) == {"resolved", "rejected", "merged"}
    for status in TERMINAL_STATUSES:
        assert f"'{status}'" in predicate
    assert predicate.startswith("status not in (")


def test_active_area_sql_qualifies_with_an_alias() -> None:
    """Joined queries get the column qualified so 'status' stays unambiguous."""
    assert active_area_sql("a").startswith("a.status not in (")
    assert active_area_sql() == active_area_sql("")


def test_resolved_area_still_seeds_a_version_chain() -> None:
    """A second fire at the same place within the hour becomes 'Area 1.2'.

    So 'resolved' must NOT be excluded from the versioning lookup, while 'rejected'
    and 'merged' must be.
    """
    predicate = versionable_area_sql()
    assert "'resolved'" not in predicate
    assert "'rejected'" in predicate
    assert "'merged'" in predicate
    assert set(UNVERSIONABLE_STATUSES) < set(TERMINAL_STATUSES)


def test_areas_active_index_matches_the_app_predicate() -> None:
    """The partial index behind the live feed must exclude the same statuses.

    If they drift, the index silently stops covering the query it exists for.
    """
    migrations = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    definitions = [
        text
        for path in sorted(migrations.glob("*.sql"))
        if "areas_active_idx" in (text := path.read_text(encoding="utf-8"))
    ]
    assert definitions, "no migration defines areas_active_idx"
    latest = definitions[-1]
    predicate = latest.split("create index areas_active_idx")[-1]
    for status in TERMINAL_STATUSES:
        assert f"'{status}'" in predicate


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/areas"),
        ("get", f"/areas/{uuid4()}"),
        ("get", "/areas/overlaps/pending"),
        ("post", f"/areas/overlaps/{uuid4()}/merge"),
        ("post", f"/areas/overlaps/{uuid4()}/keep-separate"),
    ],
)
def test_area_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    """Area + overlap endpoints require authentication."""
    assert client.request(method, path).status_code == 401