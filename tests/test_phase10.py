"""Phase 10 (WebSocket real-time) unit + guard tests (hermetic)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.routes.ws import authorize_channel
from app.main import app
from app.realtime.manager import ConnectionManager
from app.schemas.auth import AuthenticatedUser


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """TestClient bound to the app (runs startup/shutdown lifespan)."""
    with TestClient(app) as test_client:
        yield test_client


class _FakeWS:
    """Minimal stand-in for a Starlette WebSocket that records sent payloads."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


def _user(role: str, agency: str | None = None) -> AuthenticatedUser:
    """Build a minimal AuthenticatedUser."""
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency)


# --------------------------------------------------------------------------- #
# ConnectionManager
# --------------------------------------------------------------------------- #
def test_manager_broadcast_then_unsubscribe() -> None:
    """A subscriber receives broadcasts; after unsubscribe it does not."""

    async def scenario() -> tuple[int, int, list[dict[str, Any]], int]:
        m = ConnectionManager()
        ws = _FakeWS()
        conn = m.connect(ws, _user("admin"))  # type: ignore[arg-type]
        m.subscribe(conn, "incident:a")
        first = await m.broadcast("incident:a", {"n": 1})
        m.unsubscribe(conn, "incident:a")
        second = await m.broadcast("incident:a", {"n": 2})
        return first, second, ws.sent, m.channel_size("incident:a")

    first, second, sent, size = asyncio.run(scenario())
    assert first == 1
    assert second == 0
    assert sent == [{"n": 1}]
    assert size == 0


def test_manager_disconnect_clears_all_channels() -> None:
    """Disconnecting removes the connection from every channel it joined."""

    async def scenario() -> tuple[int, int]:
        m = ConnectionManager()
        ws = _FakeWS()
        conn = m.connect(ws, _user("sub_admin", "fire_volunteer"))  # type: ignore[arg-type]
        m.subscribe(conn, "incident:a")
        m.subscribe(conn, "role:sub_admin")
        m.disconnect(conn)
        return m.channel_size("incident:a"), m.channel_size("role:sub_admin")

    a, b = asyncio.run(scenario())
    assert a == 0
    assert b == 0


def test_manager_broadcast_to_empty_channel() -> None:
    """Broadcasting to a channel with no members reaches zero connections."""

    async def scenario() -> int:
        m = ConnectionManager()
        return await m.broadcast("incident:none", {"x": 1})

    assert asyncio.run(scenario()) == 0


# --------------------------------------------------------------------------- #
# Channel authorization (non-incident channels need no DB)
# --------------------------------------------------------------------------- #
def test_authorize_channel_rules() -> None:
    """Admin may join anything; others are scoped to their own role/agency."""

    async def scenario() -> dict[str, bool]:
        admin = _user("admin")
        sub = _user("sub_admin", "fire_volunteer")
        return {
            "admin_any": await authorize_channel(admin, f"incident:{uuid4()}", None),  # type: ignore[arg-type]
            "own_role": await authorize_channel(sub, "role:sub_admin", None),  # type: ignore[arg-type]
            "other_role": await authorize_channel(sub, "role:admin", None),  # type: ignore[arg-type]
            "own_agency": await authorize_channel(sub, "agency:fire_volunteer", None),  # type: ignore[arg-type]
            "other_agency": await authorize_channel(sub, "agency:police", None),  # type: ignore[arg-type]
            "garbage": await authorize_channel(sub, "not-a-channel", None),  # type: ignore[arg-type]
        }

    r = asyncio.run(scenario())
    assert r["admin_any"] is True
    assert r["own_role"] is True
    assert r["other_role"] is False
    assert r["own_agency"] is True
    assert r["other_agency"] is False
    assert r["garbage"] is False


# --------------------------------------------------------------------------- #
# WS upgrade auth
# --------------------------------------------------------------------------- #
def test_ws_rejects_missing_token(client: TestClient) -> None:
    """Connecting without a token is rejected on the upgrade."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass


def test_ws_rejects_invalid_token(client: TestClient) -> None:
    """Connecting with a malformed token is rejected on the upgrade."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=not-a-valid-jwt"):
            pass