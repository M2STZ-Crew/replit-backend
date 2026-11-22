"""Who hears a fire code, and how (v1.12.46).

20 Nov 2026: "if they press the fire code, there's nothing happening". A press
was saved and sent on a channel nobody read. Answered: "Show it and alert",
"By what the code asks", and Admins press from the console too. So a press is
on the incident everywhere (IncidentDetail.fire_codes, the incident's own
broadcast) and alerts, in each reader's language:

- FC-6 Water supply needed: Fire Volunteer and BFP coordinators;
- FC-7 Additional units needed: coordinators of every agency on the incident;
- FC-8 Possible casualty: medical coordinators and the central hub;
- FC-1 to FC-5 (on scene, under control, fire out, overhauling, returning):
  the incident's crews and the coordinators of its agencies, without a sound.

Never the person who pressed it. Codes that ask for help ring with the fire
alarm; the rest only vibrate. The incident's status never changes.
Best-effort: the press stands whether or not anyone is told.
"""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, token_versions
from app.services import staff_copy
from app.services.access import FIRE_AGENCIES
from app.services.citizen_copy import by_language, languages_of
from app.services.notification_inbox import record_inbox
from app.services.org_standing import not_frozen_sql

log = get_logger(__name__)

WATER = "FC-6"
MORE_UNITS = "FC-7"
CASUALTY = "FC-8"
# Codes that ask for something: they ring. The others report progress.
ASKS = frozenset({WATER, MORE_UNITS, CASUALTY})

# The agencies an incident is on: what its reports asked for, and Fire
# Volunteer and BFP for each other (they see each other's fires).
_AGENCIES_SQL = """
select coalesce(array_agg(distinct a::text), '{}')
  from public.area_reports ar
  join public.reports r on r.id = ar.report_id,
       unnest(r.selected_agencies) as a
 where ar.area_id = $1
"""

_COORDINATORS_SQL = f"""
select u.id from public.users u
 where u.role = 'sub_admin' and u.is_active and {not_frozen_sql()}
   and u.agency_type::text = any($1::text[])
"""

# Responders on their way to it or at it.
_CREWS_SQL = f"""
select distinct d.responder_id from public.dispatch_logs d
  join public.users u on u.id = d.responder_id
 where d.area_id = $1 and d.status = 'active' and {not_frozen_sql()}
"""

_HUB_SQL = """
select u.id from public.users u
  join public.organizations o on o.id = u.primary_org_id
 where o.is_central_hub and u.is_active and u.role in ('sub_admin', 'response_team')
"""


async def _agencies_on(db: Database, area_id: UUID) -> list[str]:
    agencies = set(await db.fetchval(_AGENCIES_SQL, area_id) or [])
    if agencies & set(FIRE_AGENCIES):
        agencies |= set(FIRE_AGENCIES)
    return sorted(agencies)


async def recipients(db: Database, area_id: UUID, code_number: str, pressed_by: UUID) -> list[UUID]:
    """Whoever this code is for, never the presser."""
    ids: set[UUID] = set()
    if code_number == WATER:
        ids |= {r["id"] for r in await db.fetch(_COORDINATORS_SQL, list(FIRE_AGENCIES))}
    elif code_number == MORE_UNITS:
        agencies = await _agencies_on(db, area_id)
        ids |= {r["id"] for r in await db.fetch(_COORDINATORS_SQL, agencies)}
    elif code_number == CASUALTY:
        ids |= {r["id"] for r in await db.fetch(_COORDINATORS_SQL, ["medical"])}
        ids |= {r["id"] for r in await db.fetch(_HUB_SQL)}
    else:
        agencies = await _agencies_on(db, area_id)
        ids |= {r["id"] for r in await db.fetch(_COORDINATORS_SQL, agencies)}
        ids |= {r["responder_id"] for r in await db.fetch(_CREWS_SQL, area_id)}
    ids.discard(pressed_by)
    return sorted(ids, key=str)


async def notify_fire_code(
    db: Database,
    area_id: UUID,
    code_number: str,
    code_name: str,
    pressed_by: UUID,
) -> int:
    """Inbox and push the people [code_number] is for. Returns how many."""
    ids = await recipients(db, area_id, code_number, pressed_by)
    if not ids:
        return 0
    area = await db.fetchrow("select designation from public.areas where id = $1", area_id)
    who = await db.fetchrow(
        """
        select u.full_name, o.name as org
          from public.users u
          left join public.organizations o on o.id = u.primary_org_id
         where u.id = $1
        """,
        pressed_by,
    )
    designation = area["designation"] if area else None
    name = who["full_name"] if who else None
    org = who["org"] if who else None
    data = {"type": "fire_code", "area_id": str(area_id), "code": code_number}
    languages = await languages_of(db, ids)
    for language, group in by_language(languages).items():
        title, body = staff_copy.fire_code(language, code_number, code_name, name, org, designation)
        await record_inbox(db, group, "fire_code", title, body, dict(data))

    token_rows = await db.fetch(
        "select user_id, fcm_token, app_version from public.device_tokens "
        "where user_id = any($1::uuid[]) and is_active",
        ids,
    )
    push = PushService()
    asks = code_number in ASKS
    for language, group in by_language(languages).items():
        members = set(group)
        rows = [t for t in token_rows if t["user_id"] in members]
        if not rows:
            continue
        title, body = staff_copy.fire_code(language, code_number, code_name, name, org, designation)
        result = await push.send_to_tokens(
            tokens=[t["fcm_token"] for t in rows],
            title=title,
            body=body,
            data=data,
            sound="fire" if asks else None,
            silent=not asks,
            # One per code and incident in the shade: a repeat replaces it.
            tag=f"code-{area_id}-{code_number}",
            versions=token_versions(rows),
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    log.info("fire_code_notified", area_id=str(area_id), code=code_number, people=len(ids))
    return len(ids)
