"""Phase 9 (incident lifecycle) unit + guard tests (hermetic)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services.incident import ALLOWED_TRANSITIONS, assert_transition, visible_agencies


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


def _user(role: str, agency: str | None = None) -> AuthenticatedUser:
    """Build a minimal AuthenticatedUser for visibility tests."""
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency)


# --------------------------------------------------------------------------- #
# Visibility helper (BFP <-> Fire-Vol two-way)
# --------------------------------------------------------------------------- #
def test_visible_agencies_admin_sees_all() -> None:
    """Admin has no agency filter (None == all)."""
    assert visible_agencies(_user("admin")) is None


def test_visible_agencies_fire_is_two_way() -> None:
    """Fire Volunteer and BFP each see both fire agencies."""
    assert set(visible_agencies(_user("sub_admin", "fire_volunteer")) or []) == {
        "fire_volunteer",
        "bfp",
    }
    assert set(visible_agencies(_user("response_team", "bfp")) or []) == {
        "fire_volunteer",
        "bfp",
    }


def test_visible_agencies_other_agency_is_scoped() -> None:
    """A non-fire agency sees only its own incidents."""
    assert visible_agencies(_user("sub_admin", "police")) == ["police"]


def test_visible_agencies_no_agency_sees_nothing() -> None:
    """A non-admin with no agency is scoped to the empty set."""
    assert visible_agencies(_user("response_team", None)) == []


# --------------------------------------------------------------------------- #
# Lifecycle state machine
# --------------------------------------------------------------------------- #
def test_assert_transition_allows_the_forward_path() -> None:
    """The full pending -> verified -> ... -> resolved chain is allowed."""
    assert_transition("pending", "verified")
    assert_transition("verified", "dispatched")
    assert_transition("dispatched", "en_route")
    assert_transition("en_route", "arrived")
    assert_transition("arrived", "resolved")


def test_assert_transition_blocks_illegal_moves() -> None:
    """Skipping states or moving out of a terminal state raises 409."""
    with pytest.raises(ConflictError):
        assert_transition("pending", "resolved")
    with pytest.raises(ConflictError):
        assert_transition("arrived", "dispatched")
    with pytest.raises(ConflictError):
        assert_transition("resolved", "verified")


def test_terminal_states_have_no_transitions() -> None:
    """resolved and rejected are dead-ends."""
    assert ALLOWED_TRANSITIONS["resolved"] == set()
    assert ALLOWED_TRANSITIONS["rejected"] == set()


# --------------------------------------------------------------------------- #
# Auth guards (every incident route requires a bearer token)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/incidents", None),
        ("get", f"/incidents/{uuid4()}", None),
        ("post", f"/incidents/{uuid4()}/verify", None),
        ("post", f"/incidents/{uuid4()}/reject", {"reason": "x"}),
        ("post", f"/incidents/{uuid4()}/resolve", None),
        ("post", f"/incidents/{uuid4()}/dispatch", {"responder_id": str(uuid4())}),
        ("post", f"/incidents/{uuid4()}/self-dispatch", {}),
        ("post", f"/incidents/{uuid4()}/en-route", None),
        ("post", f"/incidents/{uuid4()}/arrived", None),
        ("get", f"/incidents/{uuid4()}/dispatches", None),
        ("post", f"/incidents/{uuid4()}/dispatches/{uuid4()}/withdraw", None),
        (
            "post",
            f"/incidents/{uuid4()}/location",
            {"lat": 14.5, "lng": 120.9, "captured_at": "2026-06-23T00:00:00Z"},
        ),
        ("get", f"/incidents/{uuid4()}/responders/locations", None),
    ],
)
def test_incident_endpoints_require_auth(
    client: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Unauthenticated access to any incident route is rejected with 401."""
    resp = (
        client.request(method, path, json=body)
        if body is not None
        else client.request(method, path)
    )
    assert resp.status_code == 401