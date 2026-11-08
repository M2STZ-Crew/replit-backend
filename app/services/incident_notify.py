"""Citizen-facing FCM pushes for incident lifecycle changes.

When staff act on an incident (verify / dispatch / en route / arrived / resolve /
reject), the citizens who reported it get a push — delivered even when the app is
closed (FCM notification payload). Complements the 150 m neighborhood worker,
which notifies *neighbors* (and excludes the reporter).

v1.12.6: staff hear about a new fire. Under v10 a responder learnt of an
incident from the dispatch push; v11 removed dispatch, and with it the only push
staff ever got for a new fire. Now every active responder and coordinator whose
agency can see the incident gets one, with the fire alarm, the moment the first
report makes it.

v1.12.9: each hears their own agency's recording, and a coordinator who does
not open it is reminded (app/workers/coordinator_pings.py). Residents' pushes
play the citizen recording.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, SoundCategory, sound_for_agency
from app.schemas.alarm import AlarmRequestResponse, alarm_label
from app.services import staff_copy
from app.services.citizen_copy import (
    DEFAULT_LANGUAGE,
    REPORTER_MESSAGES,
    Language,
    by_language,
    language_of,
    languages_of,
    verified_by,
)
from app.services.incident import COORDINATING_AGENCIES, OBSERVER_AGENCIES
from app.services.notification_inbox import record_inbox
from app.services.verifier import fetch_verifier
from app.workers.coordinator_pings import start_pings

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
    """Inbox + push, with their agency's alarm, every staff member who can see a new fire.

    Responders and coordinators (sub-admins) of each agency that can see it,
    active accounts only; coordinators are then reminded until they open it.
    Best-effort. Returns the number of staff notified.
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
        select u.id, u.role::text as role, u.agency_type::text as agency_type
        from public.users u
        where u.role in ('sub_admin', 'response_team')
          and u.is_active
          and u.agency_type = any($1::public.agency_type[])
        """,
        agencies,
    )
    staff_ids = [r["id"] for r in staff_rows]
    if not staff_ids:
        return 0

    data = {"area_id": str(area_id), "event": "incident_new"}
    # In each one's language (staff_copy); the sound is still their agency's.
    languages = await languages_of(db, staff_ids)
    for language, ids in by_language(languages).items():
        title, body = staff_copy.new_fire(language, area["designation"])
        await record_inbox(db, ids, "incident_new", title, body, data)

    sound_of = {r["id"]: sound_for_agency(r["agency_type"]) for r in staff_rows}
    token_rows = await db.fetch(
        "select user_id, fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        staff_ids,
    )
    groups: dict[tuple[Language, SoundCategory], list[str]] = {}
    for t in token_rows:
        key = (
            languages.get(t["user_id"], DEFAULT_LANGUAGE),
            sound_of.get(t["user_id"], "fire"),
        )
        groups.setdefault(key, []).append(t["fcm_token"])
    push = PushService()
    for (language, sound), tokens in groups.items():
        title, body = staff_copy.new_fire(language, area["designation"])
        result = await push.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "incident_new", **data},
            sound=sound,
            tag=f"incident-{area_id}",
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )

    coordinators = [r["id"] for r in staff_rows if r["role"] == "sub_admin"]
    if coordinators:
        try:
            await start_pings(db, area_id, coordinators)
        except Exception:
            log.error("coordinator_pings_start_failed", area_id=str(area_id), exc_info=True)
    log.info(
        "staff_new_incident_notified",
        area_id=str(area_id),
        staff=len(staff_ids),
        devices=len(token_rows),
    )
    return len(staff_ids)

# Broadcast event_type -> (title, body) for the citizen who filed the report, in
# English; citizen_copy.REPORTER_MESSAGES has both languages.
_REPORTER_MESSAGES: dict[str, tuple[str, str]] = {
    event: texts["en"] for event, texts in REPORTER_MESSAGES.items()
}

# Keep existing lifecycle triggers; only select a distinct sound for each event.
# 9 November: a rejected report has its own recording, where it played the
# general "Report updates" one.
_REPORTER_SOUNDS: dict[str, SoundCategory] = {
    "incident_verified": "verified",
    "incident_en_route": "on_route",
    "incident_arrived": "on_scene",
    "incident_resolved": "fire_out",
    "incident_rejected": "rejected",
}


async def notify_incident_reporters(db: Database, area_id: UUID, event_type: str) -> int:
    """Push a lifecycle update to the citizens who reported ``area_id``.

    No-op for events not in [_REPORTER_MESSAGES]. Deactivates dead tokens.
    Returns the number of device tokens targeted.
    """
    texts = REPORTER_MESSAGES.get(event_type)
    if texts is None:
        return 0

    # Say which team: "...verified by Hercules Fire Brigade." Never the person.
    team: str | None = None
    if event_type == "incident_verified":
        verifier = await fetch_verifier(db, area_id)
        if verifier is not None:
            team = verifier.public_label

    def message(language: Language) -> tuple[str, str]:
        title, body = texts[language]
        return title, (verified_by(language, team) if team else body)

    data = {"area_id": str(area_id), "event": event_type}

    # In-app inbox for every reporter (even those without a device token), in
    # the language each reads the app in.
    reporter_rows = await db.fetch(
        """
        select distinct r.reporter_id as user_id, u.language
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        left join public.users u on u.id = r.reporter_id
        where ar.area_id = $1 and r.reporter_id is not null
        """,
        area_id,
    )
    reporters = {r["user_id"]: language_of(r.get("language")) for r in reporter_rows}
    for language, ids in by_language(reporters).items():
        title, body = message(language)
        await record_inbox(db, ids, "incident_update", title, body, data)

    rows = await db.fetch(
        """
        select distinct dt.fcm_token, u.language
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        join public.device_tokens dt on dt.user_id = r.reporter_id
        left join public.users u on u.id = r.reporter_id
        where ar.area_id = $1 and r.reporter_id is not null and dt.is_active
        """,
        area_id,
    )
    tokens = [r["fcm_token"] for r in rows]
    if not tokens:
        return 0
    by_tongue: dict[Language, list[str]] = {}
    for r in rows:
        by_tongue.setdefault(language_of(r.get("language")), []).append(r["fcm_token"])

    push = PushService()
    for language, group in by_tongue.items():
        title, body = message(language)
        result = await push.send_to_tokens(
            tokens=group,
            title=title,
            body=body,
            data={"type": "incident_update", **data},
            sound=_REPORTER_SOUNDS.get(event_type, "citizen"),
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
    language = (await languages_of(db, [responder_id])).get(responder_id, DEFAULT_LANGUAGE)
    title, body = staff_copy.dispatched(language, designation, crew_role, vehicle_name)

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
    languages = await languages_of(db, captain_ids)
    # Its own type, not the citizens' "incident_update": the mobile app opens a
    # citizen's live tracker for that one, which is the wrong screen for a captain.
    for language, ids in by_language(languages).items():
        title, body = staff_copy.routed(language, designation)
        await record_inbox(
            db, ids, "incident_routed", title, body,
            {"area_id": str(area_id), "event": "incident_routed"},
        )
    token_rows = await db.fetch(
        "select user_id, fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        captain_ids,
    )
    push = PushService()
    for language, tokens in _tokens_by_language(token_rows, languages).items():
        title, body = staff_copy.routed(language, designation)
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


def _tokens_by_language(
    token_rows: list[Any], languages: dict[UUID, Language]
) -> dict[Language, list[str]]:
    """Device tokens (rows of user_id, fcm_token) grouped by their owner's language."""
    groups: dict[Language, list[str]] = {}
    for t in token_rows:
        language = languages.get(t["user_id"], DEFAULT_LANGUAGE)
        groups.setdefault(language, []).append(t["fcm_token"])
    return groups


async def notify_bfp_alarm_request(
    db: Database,
    area_id: UUID,
    requested_by: UUID,
    requested_alarm_level: str,
    *,
    request_id: UUID | None = None,
    organization: str | None = None,
) -> int:
    """Inbox + push the BFP sub-admins when an alarm escalation is requested.

    Best-effort. Returns the number of BFP sub-admins notified. The push names
    the request, so a tap opens it; its tag is the Area's, so a newer request
    for the same Area replaces the older one in the shade rather than stacking.
    """
    designation = await db.fetchval(
        "select designation from public.areas where id = $1", area_id
    )
    requester = await db.fetchval(
        "select full_name from public.users where id = $1", requested_by
    )
    level_label = alarm_label(requested_alarm_level)
    # A BFP Coordinator who asked is not alerted by their own request.
    bfp_rows = await db.fetch(
        "select id from public.users "
        "where role = 'sub_admin' and agency_type = 'bfp' and id <> $1",
        requested_by,
    )
    bfp_ids = [r["id"] for r in bfp_rows]
    if not bfp_ids:
        return 0

    data = {"type": "alarm_request", "area_id": str(area_id)}
    if request_id is not None:
        data["request_id"] = str(request_id)
    languages = await languages_of(db, bfp_ids)
    for language, ids in by_language(languages).items():
        title, body = staff_copy.alarm_requested(
            language, requester, organization, level_label, designation
        )
        await record_inbox(db, ids, "alarm_request", title, body, dict(data))
    token_rows = await db.fetch(
        "select user_id, fcm_token from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        bfp_ids,
    )
    push = PushService()
    for language, tokens in _tokens_by_language(token_rows, languages).items():
        title, body = staff_copy.alarm_requested(
            language, requester, organization, level_label, designation
        )
        result = await push.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            # A fire getting bigger: the alarm, like a new one.
            sound="fire",
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


async def notify_alarm_request_answered(db: Database, request: AlarmRequestResponse) -> int:
    """Tell whoever asked for the alarm what BFP decided (inbox + push).

    The phone's own tone, not the alarm: it is an answer, not a new fire. The
    push names the Area, so a tap opens its LIVE screen, and its tag is the
    request's, so a repeat never stacks. Best-effort; returns the devices sent to.
    """
    if request.status not in ("approved", "rejected"):
        return 0
    language = (await languages_of(db, [request.requested_by])).get(
        request.requested_by, DEFAULT_LANGUAGE
    )
    title, body = staff_copy.alarm_answered(
        language,
        request.status == "approved",
        alarm_label(request.requested_alarm_level),
        request.area_designation,
        request.review_notes if request.status == "rejected" else None,
    )
    data = {
        "type": "alarm_request_answered",
        "area_id": str(request.area_id),
        "request_id": str(request.id),
        "status": request.status,
    }
    await record_inbox(db, [request.requested_by], "alarm_request_answered", title, body, data)
    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens where user_id = $1 and is_active",
        request.requested_by,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if not tokens:
        return 0
    result = await PushService().send_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data=data,
        tag=f"alarm-answer-{request.id}",
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info(
        "alarm_request_answer_notified",
        request_id=str(request.id),
        status=request.status,
        devices=len(tokens),
    )
    return len(tokens)
