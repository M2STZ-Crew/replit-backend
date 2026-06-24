"""WebSocket real-time endpoint (Phase 10, Section 8/10).

Authenticates the Supabase access token on the upgrade (``/ws?token=<jwt>`` or an
``Authorization: Bearer`` header), then runs a subscribe / unsubscribe / ping /
location protocol over JSON text frames. Subscribable channels are bounded by the
same agency-visibility rules as the REST incident feed. A response_team member may
push GPS fixes ('location'), which are persisted and fanned out to the incident
channel. A periodic server ping keeps idle connections alive.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.db.session import Database, database
from app.realtime.events import broadcast_responder_location
from app.realtime.manager import manager
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import ResponderLocationCreate
from app.services.incident import record_responder_location, visible_agencies

log = get_logger(__name__)

router = APIRouter()

_HEARTBEAT_SECONDS = 30


async def authenticate_websocket(websocket: WebSocket) -> AuthenticatedUser | None:
    """Validate the access token (?token= or Authorization) and load the user, or None."""
    token = websocket.query_params.get("token")
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
    if not token:
        return None
    try:
        claims = await decode_access_token(token, websocket.app.state.http_client)
    except Exception:
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str):
        return None
    try:
        user_id = UUID(sub)
    except ValueError:
        return None
    row = await database.fetchrow(
        """
        select id, email, phone, role, agency_type, verified_percent, badge,
               full_name, primary_org_id
        from public.users
        where id = $1
        """,
        user_id,
    )
    if row is None:
        return None
    return AuthenticatedUser.model_validate(dict(row))


async def _incident_visible(
    db: Database, incident_id: UUID, user: AuthenticatedUser
) -> bool:
    """True if the incident is visible to the user's agency (admin: always)."""
    agencies = visible_agencies(user)
    if agencies is None:
        return True
    if not agencies:
        return False
    visible = await db.fetchval(
        """
        select exists (
            select 1 from public.area_reports ar
            join public.reports r on r.id = ar.report_id
            where ar.area_id = $1
              and r.selected_agencies && $2::public.agency_type[]
        )
        """,
        incident_id,
        agencies,
    )
    return bool(visible)


async def authorize_channel(user: AuthenticatedUser, channel: str, db: Database) -> bool:
    """Decide whether a user may subscribe to a channel."""
    if user.role == "admin":
        return True
    kind, _, ident = channel.partition(":")
    if not ident:
        return False
    if kind == "incident":
        try:
            incident_id = UUID(ident)
        except ValueError:
            return False
        return await _incident_visible(db, incident_id, user)
    if kind == "role":
        return ident == user.role
    if kind == "agency":
        return ident == user.agency_type
    if kind == "org":
        return user.primary_org_id is not None and str(user.primary_org_id) == ident
    return False


async def _heartbeat(websocket: WebSocket) -> None:
    """Send a periodic ping so idle connections (and proxies) stay alive."""
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            await websocket.send_json({"type": "ping"})
    except Exception:
        return


async def _handle_location(conn_id: str, user: AuthenticatedUser, msg: dict[str, object]) -> None:
    """Persist and fan out a responder GPS fix received over the socket."""
    if user.role != "response_team":
        await manager.send_personal(
            conn_id, {"type": "error", "message": "Only responders may stream location."}
        )
        return
    try:
        incident_id = UUID(str(msg.get("incident_id")))
    except (ValueError, TypeError):
        await manager.send_personal(
            conn_id, {"type": "error", "message": "Missing or invalid incident_id."}
        )
        return
    try:
        payload = ResponderLocationCreate.model_validate(msg)
    except ValidationError:
        await manager.send_personal(
            conn_id, {"type": "error", "message": "Invalid location payload."}
        )
        return
    recorded = await record_responder_location(database, incident_id, user.id, payload)
    if not recorded:
        await manager.send_personal(
            conn_id, {"type": "error", "message": "No active dispatch to this incident."}
        )
        return
    await broadcast_responder_location(
        incident_id,
        user.id,
        {
            "lat": payload.lat,
            "lng": payload.lng,
            "accuracy_m": payload.accuracy_m,
            "speed_mps": payload.speed_mps,
            "heading_deg": payload.heading_deg,
            "captured_at": payload.captured_at.isoformat(),
        },
    )
    await manager.send_personal(
        conn_id, {"type": "location_recorded", "incident_id": str(incident_id)}
    )


async def _dispatch_message(conn_id: str, user: AuthenticatedUser, raw: str) -> None:
    """Handle one inbound client frame (subscribe / unsubscribe / ping / location)."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await manager.send_personal(conn_id, {"type": "error", "message": "Invalid JSON."})
        return
    if not isinstance(msg, dict):
        await manager.send_personal(
            conn_id, {"type": "error", "message": "Expected a JSON object."}
        )
        return

    action = msg.get("action")
    if action == "ping":
        await manager.send_personal(conn_id, {"type": "pong"})
        return
    if action == "location":
        await _handle_location(conn_id, user, msg)
        return
    if action in ("subscribe", "unsubscribe"):
        channel = msg.get("channel")
        if not isinstance(channel, str) or not channel:
            await manager.send_personal(
                conn_id, {"type": "error", "message": "Missing or invalid channel."}
            )
            return
        if action == "subscribe":
            if not await authorize_channel(user, channel, database):
                await manager.send_personal(
                    conn_id,
                    {"type": "error", "message": f"Not allowed to subscribe to {channel}."},
                )
                return
            manager.subscribe(conn_id, channel)
            await manager.send_personal(conn_id, {"type": "subscribed", "channel": channel})
        else:
            manager.unsubscribe(conn_id, channel)
            await manager.send_personal(conn_id, {"type": "unsubscribed", "channel": channel})
        return

    await manager.send_personal(conn_id, {"type": "error", "message": "Unknown action."})


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Authenticated real-time channel: subscribe to feeds + stream responder GPS."""
    user = await authenticate_websocket(websocket)
    if user is None:
        log.info("ws_auth_rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    conn_id = manager.connect(websocket, user)
    await manager.send_personal(
        conn_id, {"type": "connected", "user_id": str(user.id), "role": user.role}
    )
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            raw = await websocket.receive_text()
            await _dispatch_message(conn_id, user, raw)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        manager.disconnect(conn_id)