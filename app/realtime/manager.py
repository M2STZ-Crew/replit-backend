"""In-process WebSocket connection manager (Phase 10, Section 8/10).

Tracks active WebSocket connections and their channel subscriptions, and fans out
messages to every connection subscribed to a channel. Single-process only: with
multiple Uvicorn workers each worker holds its own registry (a Redis/pub-sub
backplane is deferred to Phase 17). Channels: ``incident:<uuid>``, ``org:<uuid>``,
``role:<role>``, ``agency:<agency>``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from app.core.logging import get_logger
from app.schemas.auth import AuthenticatedUser

log = get_logger(__name__)


class ConnectionManager:
    """Registry of live WebSocket connections and their channel subscriptions."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._users: dict[str, AuthenticatedUser] = {}
        self._channel_members: defaultdict[str, set[str]] = defaultdict(set)
        self._subscriptions: defaultdict[str, set[str]] = defaultdict(set)

    def connect(self, websocket: WebSocket, user: AuthenticatedUser) -> str:
        """Register an accepted connection; return its connection id."""
        conn_id = uuid4().hex
        self._connections[conn_id] = websocket
        self._users[conn_id] = user
        log.info("ws_connected", conn_id=conn_id, user_id=str(user.id), role=user.role)
        return conn_id

    def disconnect(self, conn_id: str) -> None:
        """Remove a connection and all of its subscriptions."""
        for channel in self._subscriptions.pop(conn_id, set()):
            members = self._channel_members.get(channel)
            if members is not None:
                members.discard(conn_id)
                if not members:
                    del self._channel_members[channel]
        self._connections.pop(conn_id, None)
        self._users.pop(conn_id, None)
        log.info("ws_disconnected", conn_id=conn_id)

    def subscribe(self, conn_id: str, channel: str) -> None:
        """Add a connection to a channel."""
        self._channel_members[channel].add(conn_id)
        self._subscriptions[conn_id].add(channel)

    def unsubscribe(self, conn_id: str, channel: str) -> None:
        """Remove a connection from a channel."""
        self._subscriptions[conn_id].discard(channel)
        members = self._channel_members.get(channel)
        if members is not None:
            members.discard(conn_id)
            if not members:
                del self._channel_members[channel]

    async def send_personal(self, conn_id: str, message: dict[str, Any]) -> None:
        """Send a JSON message to one connection (no-op if it vanished)."""
        websocket = self._connections.get(conn_id)
        if websocket is not None:
            await websocket.send_json(message)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> int:
        """Send a JSON message to every connection on a channel; return how many got it."""
        sent = 0
        for conn_id in list(self._channel_members.get(channel, set())):
            websocket = self._connections.get(conn_id)
            if websocket is None:
                continue
            try:
                await websocket.send_json(message)
                sent += 1
            except Exception:
                self.disconnect(conn_id)
        return sent

    def channel_size(self, channel: str) -> int:
        """Number of connections currently subscribed to a channel."""
        return len(self._channel_members.get(channel, set()))


# Module-level singleton shared by the WS endpoint and (Part 2) the REST mutations.
manager = ConnectionManager()