"""Citizen-facing FCM pushes for incident lifecycle changes.

When staff act on an incident (verify / dispatch / en route / arrived / resolve /
reject), the citizens who reported it get a push — delivered even when the app is
closed (FCM notification payload). Complements the 300 m neighborhood worker,
which notifies *neighbors* (and excludes the reporter).

v1.12.6: staff hear about a new fire. Under v10 a responder learnt of an
incident from the dispatch push; v11 removed dispatch, and with it the only push
staff ever got for a new fire. Now every active responder and coordinator whose
agency can see the incident gets one, with the fire alarm, the moment the first
report makes it.
"""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService
from app.services.incident import COORDINATING_AGENCIES, OBSERVER_AGENCIES
from app.services.notification_inbox import record_inbox
from app.services.verifier import fetch_verifier

log = get_logger(__name__)


def staff_agencies_for(asked: list[str]) -> list[str]:
    """The staff agencies that can see an incident whose reports asked ``asked``.

    Incident visibility (``visible_agencies``) read the other way round: each
    agency sees what was asked of it, and the two fire agencies see each other's
    — so a fire asked of the Fire Volunteers reaches BFP too.
    """
    wanted = set(asked)
    fire = bool(wanted & set(COORDINATING_AGENCIES))
    return [
        agency
        for agency in (*COORDINATING_AGENCIES, *OBSERVER_AGENCIES)
        if agency in wanted or (fire and agency in COORDINATING_AGENCIES)
    ]


async def notify_staff_new_incident(db: Database, area_id: UUID) -> int:
    """Inbox + push, with the fire alarm, every staff member who can see a new fire.

    Responders and coordinators (sub-admins) of each agency that can see it,
    active accounts only. Best-effort. Returns the number of staff notified.
    """
    area = await db.fetchrow(
        """
        select a.designation,
               array(select distinct unnest(r.selected_agencies)::text
                     from public.area_reports ar
                     join public.reports r on r.id = ar.report_id
                     where ar.area_id = a.id) as asked
        from public.areas a
        where a.id = $1
        """,
        area_id,
    )
    if area is None:
        return 0
    agencies = staff_agencies_for(list(area["asked"] or []))
    if not agencies:
        return 0
    staff_rows = await db.fetch(
        """
        select u.id from public.users u
        where u.role in ('sub_admin', 'response_team')
          and u.is_active
          and u.agency_type = any($1::public.agency_type[])
        """,
        agencies,
    )
    staff_ids = [r["id"] for r in staff_rows]
    if not staff_ids:
        return 0

    title = f"Fire reported: {area['designation'] or 'new incident'}"
    body = "A resident reported a fire. Tap to open it, verify it and respond."
    data = {"area_id": str(area_id), "event": "incident_new"}
    await record_inbox(db, staff_ids, "incident_new", title, body, data)

    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        staff_ids,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if tokens:
        result = await PushService().send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "incident_new", **data},
            alert=True,
            tag=f"incident-{area_id}",
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    log.info(
        "staff_new_incident_notified",
        area_id=str(area_id),
        staff=len(staff_ids),
        devices=len(tokens),
    )
    return len(staff_ids)

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
        "Help is on the way",
        "Responders are on the way to the fire you reported. Open RepLiT to see them.",
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
    if event_type == "incident_verified":
        # Say which team: "...verified by Hercules Fire Brigade." Never the person.
        verifier = await fetch_verifier(db, area_id)
        if verifier is not None:
            body = (
                f"Your fire report was verified by {verifier.public_label}. "
                "Responders are being assigned."
            )

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
        # One per incident in the shade: the latest news replaces the last.
        tag=f"report-{area_id}",
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


async def notify_route_recipients(
    db: Database, area_id: UUID, routes: list[tuple[str, UUID | None]]
) -> int:
    """Inbox + push the team captains Admin just routed an incident to (v10 §2.6.2).

    ``routes`` holds (agency, organization_id) pairs; a null organization means
    the agency as a whole. Reaches the sub-admins — the team captains — of each
    routed team. Observer captains work from the web console, which alerts them
    with its own sound; the inbox row is what that console and the mobile bell
    read, and the push reaches any registered phone. Best-effort.
    Returns the number of captains notified.
    """
    if not routes:
        return 0
    agencies = sorted({agency for agency, _ in routes})
    org_ids = [org for _, org in routes if org is not None]
    whole_agencies = sorted({agency for agency, org in routes if org is None})
    rows = await db.fetch(
        """
        select distinct u.id
        from public.users u
        where u.role = 'sub_admin'
          and u.agency_type = any($1::public.agency_type[])
          and (u.agency_type = any($2::public.agency_type[])
               or u.primary_org_id = any($3::uuid[]))
        """,
        agencies,
        whole_agencies,
        org_ids,
    )
    captain_ids = [r["id"] for r in rows]
    if not captain_ids:
        return 0

    designation = await db.fetchval(
        "select designation from public.areas where id = $1", area_id
    )
    title = "Incident routed to your team"
    body = f"Admin routed {designation or 'an incident'} to your team. Open it to respond."
    # Its own type, not the citizens' "incident_update": the mobile app opens a
    # citizen's live tracker for that one, which is the wrong screen for a captain.
    await record_inbox(
        db, captain_ids, "incident_routed", title, body,
        {"area_id": str(area_id), "event": "incident_routed"},
    )

    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        captain_ids,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if tokens:
        push = PushService()
        result = await push.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "incident_routed", "area_id": str(area_id)},
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    log.info("route_recipients_notified", area_id=str(area_id), captains=len(captain_ids))
    return len(captain_ids)


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
            # A fire getting bigger: the alarm, like a new one.
            alert=True,
            tag=f"alarm-{area_id}",
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    log.info("bfp_alarm_request_notified", area_id=str(area_id), bfp=len(bfp_ids))
    return len(bfp_ids)
