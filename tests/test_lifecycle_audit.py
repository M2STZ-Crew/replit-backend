"""Incident lifecycle transitions audit themselves, inside their own transaction (hermetic).

Verify, reject, resolve, dispatch, self-dispatch, en-route and arrived used to be
recorded by the request middleware, which runs after the response, swallows its
own errors and cannot see the incident's status. So a lifecycle action could
succeed with no audit row, and the rows it did write carried no before/after
state (Section 4.1). These guard the replacement: the status is read under a row
lock, and the row written alongside the change records where it moved from and to.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import Request

from app.api.routes.incidents import _audit_transition, _lock_status
from app.core.exceptions import NotFoundError
from app.schemas.auth import AuthenticatedUser


class _FakeConn:
    """Stands in for the transaction's asyncpg connection, recording what it is asked."""

    def __init__(self, status: str | None = "pending") -> None:
        self.status = status
        self.queries: list[str] = []
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def fetchval(self, query: str, *args: object) -> object:
        self.queries.append(query)
        return self.status

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"user-agent", b"pytest")],
            "client": ("127.0.0.1", 50000),
        }
    )


async def test_the_status_is_read_under_a_row_lock() -> None:
    """Two coordinators acting at once must not both pass the transition check."""
    conn = _FakeConn("dispatched")
    assert await _lock_status(conn, uuid4()) == "dispatched"
    assert "for update" in conn.queries[0]


async def test_an_incident_deleted_mid_request_is_a_404() -> None:
    with pytest.raises(NotFoundError):
        await _lock_status(_FakeConn(None), uuid4())


async def test_the_row_records_the_status_it_moved_from_and_to() -> None:
    conn = _FakeConn()
    user = AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="fire_volunteer")
    incident_id = uuid4()

    await _audit_transition(
        conn,
        _request(),
        user,
        incident_id,
        action="incident.reject",
        before="verified",
        after="rejected",
        metadata={"reason": "prank call"},
    )

    [(query, args)] = conn.executed
    assert "insert into public.audit_logs" in query
    # Columns, in order: actor, role, agency, action, entity type, entity id,
    # area id, before, after, metadata, ip, user agent, request id.
    assert args[0] == user.id
    assert args[1:3] == ("sub_admin", "fire_volunteer")
    assert args[3] == "incident.reject"
    assert args[4] == "area"
    assert args[5] == incident_id
    assert args[6] == incident_id
    assert json.loads(str(args[7])) == {"status": "verified"}
    assert json.loads(str(args[8])) == {"status": "rejected"}
    assert json.loads(str(args[9])) == {"reason": "prank call"}


async def test_a_transition_without_extra_detail_still_records_both_states() -> None:
    conn = _FakeConn()
    user = AuthenticatedUser(id=uuid4(), role="response_team", agency_type="fire_volunteer")

    await _audit_transition(
        conn, _request(), user, uuid4(), action="incident.en_route",
        before="dispatched", after="en_route",
    )

    [(_, args)] = conn.executed
    assert json.loads(str(args[7])) == {"status": "dispatched"}
    assert json.loads(str(args[8])) == {"status": "en_route"}
    assert json.loads(str(args[9])) == {}
