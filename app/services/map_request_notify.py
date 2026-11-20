"""Tell a coordinator what became of their map change (v1.12.43).

A Fire Volunteer or BFP coordinator adds, changes or switches off a water
source from the app; an Admin approves or rejects it in the console
(map_layer_requests). Since 19 Nov 2026 the coordinator hears the answer: one
alert in their language, kept in their Alerts. Best-effort: the decision
stands whether or not the alert goes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, token_versions
from app.services.citizen_copy import language_of
from app.services.notification_inbox import record_inbox
from app.services.staff_copy import map_request_decided

log = get_logger(__name__)


async def tell_requester(db: Database, request: Mapping[str, Any], *, approved: bool) -> None:
    """Push and inbox the request's answer to whoever asked."""
    requester = request.get("requested_by")
    if requester is None:
        return
    try:
        row = await db.fetchrow("select language from public.users where id = $1", requester)
        language = language_of(row["language"] if row else None)
        operation = str(request.get("operation") or "")
        # The app's "Switch off" is a change that only sets is_active false:
        # said as switching it off, not as an edit.
        if operation == "update" and request.get("proposed_data") == {"is_active": False}:
            operation = "delete"
        title, body = map_request_decided(
            language,
            approved=approved,
            layer=str(request.get("layer_type") or ""),
            operation=operation,
            notes=request.get("review_notes"),
        )
        data = {
            "request_id": str(request.get("id")),
            "layer_type": str(request.get("layer_type") or ""),
            "approved": "true" if approved else "false",
        }
        await record_inbox(db, [requester], "map_request_decided", title, body, data)
        tokens = await db.fetch(
            "select fcm_token, app_version from public.device_tokens "
            "where user_id = $1 and is_active",
            requester,
        )
        if not tokens:
            return
        # News, not an alarm: the vibrate-only channel the coordinator's
        # reminders use.
        result = await PushService().send_to_tokens(
            tokens=[t["fcm_token"] for t in tokens],
            title=title,
            body=body,
            data={"type": "map_request_decided", **data},
            silent=True,
            tag=f"map-request-{request.get('id')}",
            versions=token_versions(tokens),
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    except Exception:
        log.error("map_request_tell_failed", request_id=str(request.get("id")), exc_info=True)
