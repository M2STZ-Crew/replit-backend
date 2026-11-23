"""Who hears that the alarm was raised, and how (v1.12.49).

22 Nov 2026: the app said "Everyone on this fire sees it now" and only whoever
had asked was told. Answered "Staff loud, residents quiet":

- the crews on the fire and the coordinators of its agencies: with the fire
  alarm's sound;
- the residents who reported it, or were alerted to it: without a sound;
- Admins hear it in the console, which watches the live feed
  (admin-web/src/live/LiveFeed.jsx); they have no phone to push to.

Never whoever raised it, nor whoever asked for it: they get BFP's answer.
A withdrawn Under control is told, quietly, to the staff its FC-2 told.

Best-effort and after the answer: the level stands whether or not anyone is
told. "Alerted to it" is the 100 m alert and, since v1.12.38, the alert every
resident with the app gets once a fire is verified.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, token_versions
from app.schemas.alarm import alarm_label
from app.services import citizen_copy, staff_copy
from app.services.access import FIRE_AGENCIES
from app.services.citizen_copy import Language, by_language, languages_of
from app.services.notification_inbox import record_inbox
from app.services.org_standing import not_frozen_sql

log = get_logger(__name__)

_BATCH = 500  # FCM's most in one multicast

_STAFF_SQL = f"""
with asked as (
  select distinct unnest(r.selected_agencies)::text as agency
    from public.area_reports ar
    join public.reports r on r.id = ar.report_id
   where ar.area_id = $1
),
agencies as (
  select agency from asked
  union
  -- Fire Volunteer and BFP see each other's fires.
  select unnest($2::text[])
   where exists (select 1 from asked where agency = any($2::text[]))
)
select u.id
  from public.users u
 where u.is_active
   and {not_frozen_sql()}
   and (
     (u.role::text = 'sub_admin' and u.agency_type::text in (select agency from agencies))
     or u.id in (
       select d.responder_id from public.dispatch_logs d
        where d.area_id = $1 and d.status = 'active'
     )
   )
"""

_RESIDENTS_SQL = """
select u.id
  from public.users u
 where u.role::text = 'general_user'
   and (to_jsonb(u) ->> 'deletion_requested_at') is null
   and (
     u.id in (
       select r.reporter_id from public.area_reports ar
         join public.reports r on r.id = ar.report_id
        where ar.area_id = $1
     )
     or u.id in (
       select nn.user_id from public.neighborhood_notifications nn
        where nn.area_id = $1 and nn.alerts_sent > 0
     )
     or u.id in (
       select n.user_id from public.notifications n
        where n.type = 'fire_verified' and n.data ->> 'area_id' = $2
     )
   )
"""


async def staff_on(db: Database, area_id: UUID) -> set[UUID]:
    """The crews on the fire and the coordinators of its agencies."""
    rows = await db.fetch(_STAFF_SQL, area_id, list(FIRE_AGENCIES))
    return {row["id"] for row in rows}


async def residents_told(db: Database, area_id: UUID) -> set[UUID]:
    """The residents who reported it or were alerted to it."""
    rows = await db.fetch(_RESIDENTS_SQL, area_id, str(area_id))
    return {row["id"] for row in rows}


async def _send(
    db: Database,
    push: PushService,
    ids: Iterable[UUID],
    copy: Callable[[Language], tuple[str, str]],
    data: dict[str, str],
    *,
    loud: bool,
    tag: str,
) -> int:
    people: Sequence[UUID] = sorted(set(ids), key=str)
    if not people:
        return 0
    for language, group in by_language(await languages_of(db, people)).items():
        title, body = copy(language)
        await record_inbox(db, group, data["type"], title, body, dict(data))
        rows = await db.fetch(
            "select fcm_token, app_version from public.device_tokens "
            "where user_id = any($1::uuid[]) and is_active",
            group,
        )
        for start in range(0, len(rows), _BATCH):
            batch = rows[start : start + _BATCH]
            result = await push.send_to_tokens(
                tokens=[row["fcm_token"] for row in batch],
                title=title,
                body=body,
                data=data,
                sound="fire" if loud else None,
                silent=not loud,
                tag=tag,
                versions=token_versions(batch),
            )
            if result.invalid_tokens:
                await db.execute(
                    "update public.device_tokens set is_active = false "
                    "where fcm_token = any($1::text[])",
                    result.invalid_tokens,
                )
    return len(people)


async def notify_alarm_raised(
    db: Database,
    area_id: UUID,
    level: str,
    raised_by: UUID,
    *,
    already_told: Iterable[UUID] = (),
    push: PushService | None = None,
) -> tuple[int, int]:
    """Tell the fire's staff aloud and its residents quietly; how many of each."""
    designation = await db.fetchval("select designation from public.areas where id = $1", area_id)
    organization = await db.fetchval(
        "select o.name from public.users u "
        "join public.organizations o on o.id = u.primary_org_id where u.id = $1",
        raised_by,
    )
    skip = {raised_by, *already_told}
    staff = await staff_on(db, area_id) - skip
    residents = await residents_told(db, area_id) - skip - staff
    word = alarm_label(level)
    data = {"type": "alarm_raised", "area_id": str(area_id), "alarm_level": level}
    push = push or PushService()
    tag = f"alarm-{area_id}"
    loud = await _send(
        db, push, staff,
        lambda language: staff_copy.alarm_raised(language, word, designation, organization),
        data, loud=True, tag=tag,
    )
    quiet = await _send(
        db, push, residents,
        lambda language: citizen_copy.alarm_raised(
            language, word, designation, highest=level == "general_alarm"
        ),
        data, loud=False, tag=tag,
    )
    log.info("alarm_raise_notified", area_id=str(area_id), staff=loud, residents=quiet)
    return loud, quiet


async def notify_under_control_withdrawn(
    db: Database, area_id: UUID, withdrawn_by: UUID, *, push: PushService | None = None
) -> int:
    """Correct the FC-2 its staff were sent, as quietly as it came."""
    designation = await db.fetchval("select designation from public.areas where id = $1", area_id)
    told = await _send(
        db,
        push or PushService(),
        await staff_on(db, area_id) - {withdrawn_by},
        lambda language: staff_copy.under_control_withdrawn(language, designation),
        {"type": "under_control_withdrawn", "area_id": str(area_id)},
        loud=False,
        tag=f"code-{area_id}-FC-2",  # replaces that code's alert in the shade
    )
    log.info("under_control_withdrawal_notified", area_id=str(area_id), staff=told)
    return told
