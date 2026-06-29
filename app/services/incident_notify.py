"""Citizen-facing FCM pushes for incident lifecycle changes.

When staff act on an incident (verify / dispatch / en route / arrived / resolve /
reject), the citizens who reported it get a push — delivered even when the app is
closed (FCM notification payload). Complements the 300 m neighborhood worker,
which notifies *neighbors* (and excludes the reporter).
"""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

# Broadcast event_type -> (title, body) for the citizen who filed the report.
_REPORTER_MESSAGES: dict[str, tuple[str, str]] = {
    "incident_verified": (
        "Report verified",
        "Your fire report was verified. Responders are being assigned.",
    ),
    "responder_dispatched": (
        "Responders dispatched",
        "A response team has been dispatched to the incident you reported.",
    ),
    "incident_en_route": (
        "Responders en route",
        "Help is on the way to your reported location.",
    ),
    "incident_arrived": (
        "Responders on scene",
        "Responders have arrived at the incident you reported.",
    ),
    "incident_resolved": (
        "Incident resolved",
        "The incident you reported has been resolved. Stay safe.",
    ),
    "incident_rejected": (
        "Report closed",
        "Your report has been reviewed and closed.",
    ),
}


async def notify_incident_reporters(db: Database, area_id: UUID, event_type: str) -> int:
    """Push a lifecycle update to the citizens who reported ``area_id``.

    No-op for events not in [_REPORTER_MESSAGES]. Deactivates dead tokens.
    Returns the number of device tokens targeted.
    """
    message = _REPORTER_MESSAGES.get(event_type)
    if message is None:
        return 0

    title, body = message

    # In-app inbox for every reporter (even those without a device token).
    reporter_rows = await db.fetch(
        """
        select distinct r.reporter_id as user_id
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        where ar.area_id = $1 and r.reporter_id is not null
        """,
        area_id,
    )
    await record_inbox(
        db,
        [r["user_id"] for r in reporter_rows],
        "incident_update",
        title,
        body,
        {"area_id": str(area_id), "event": event_type},
    )

    rows = await db.fetch(
        """
        select distinct dt.fcm_token
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        join public.device_tokens dt on dt.user_id = r.reporter_id
        where ar.area_id = $1 and r.reporter_id is not null and dt.is_active
        """,
        area_id,
    )
    tokens = [r["fcm_token"] for r in rows]
    if not tokens:
        return 0

    push = PushService()
    result = await push.send_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "incident_update", "area_id": str(area_id), "event": event_type},
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info(
        "incident_reporters_notified",
        area_id=str(area_id),
        lifecycle_event=event_type,
        devices=len(tokens),
    )
    return len(tokens)


async def notify_responder_dispatched(
    db: Database,
    responder_id: UUID,
    area_id: UUID,
    vehicle_name: str | None = None,
    crew_role: str | None = None,
) -> int:
    """Push the manually-dispatched responder that they've been assigned.

    Best-effort. Deactivates dead tokens. Returns the number of devices targeted.
    """
    designation = await db.fetchval(
        "select designation from public.areas where id = $1", area_id
    )
    where = designation or "an incident"
    detail_parts: list[str] = []
    if crew_role:
        detail_parts.append(crew_role)
    if vehicle_name:
        detail_parts.append(f"on {vehicle_name}")
    suffix = f" — {' '.join(detail_parts)}" if detail_parts else ""
    title = "You've been dispatched"
    body = f"Respond to {where}{suffix}."

    await record_inbox(
        db, [responder_id], "responder_dispatch", title, body, {"area_id": str(area_id)}
    )

    rows = await db.fetch(
        "select fcm_token from public.device_tokens where user_id = $1 and is_active",
        responder_id,
    )
    tokens = [r["fcm_token"] for r in rows]
    if not tokens:
        return 0

    push = PushService()
    result = await push.send_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "responder_dispatch", "area_id": str(area_id)},
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info(
        "responder_dispatch_notified",
        area_id=str(area_id),
        responder_id=str(responder_id),
        devices=len(tokens),
    )
    return len(tokens)


async def notify_bfp_alarm_request(
    db: Database, area_id: UUID, requested_by: UUID, requested_alarm_level: str
) -> int:
    """Inbox + push the BFP sub-admins when an alarm escalation is requested.

    Best-effort. Returns the number of BFP sub-admins notified.
    """
    designation = await db.fetchval(
        "select designation from public.areas where id = $1", area_id
    )
    requester = await db.fetchval(
        "select full_name from public.users where id = $1", requested_by
    )
    level_label = requested_alarm_level.replace("_", " ").title()
    bfp_rows = await db.fetch(
        "select id from public.users where role = 'sub_admin' and agency_type = 'bfp'"
    )
    bfp_ids = [r["id"] for r in bfp_rows]
    if not bfp_ids:
        return 0

    title = "Alarm escalation requested"
    body = (
        f"{requester or 'A responder'} requested {level_label} for "
        f"{designation or 'an incident'}."
    )
    await record_inbox(db, bfp_ids, "alarm_request", title, body, {"area_id": str(area_id)})

    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        bfp_ids,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if tokens:
        push = PushService()
        result = await push.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "alarm_request", "area_id": str(area_id)},
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    log.info("bfp_alarm_request_notified", area_id=str(area_id), bfp=len(bfp_ids))
    return len(bfp_ids)
