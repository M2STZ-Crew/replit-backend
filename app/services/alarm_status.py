"""A fire's alarm status, as every screen shows it (v1.12.49).

22 Nov 2026: "fire alarm status can be seen in any details info. because it is
essential to be seen by anyone"; answered "Level + situation" and "Everyone,
everywhere". The status is BFP's level, and Under control while that is in
effect:

- declared by a fire coordinator or Admin (app/services/under_control.py);
- on a live fire (acknowledged, on route or arrived): fire out says more;
- newer than the alarm level, so a raise clears it with nothing to write.

The columns are read through to_jsonb, so every read works on a database
without migration 20261122090000: nobody is under control there. Residents
get the organisation, never the person.
"""

from __future__ import annotations

UNDER_CONTROL_CODE = "FC-2"
# The statuses a fire can be under control in.
LIVE = ("verified", "en_route", "arrived")

_LIVE_SQL = ", ".join(f"'{status}'" for status in LIVE)


def under_control_at_sql(alias: str = "a") -> str:
    """When it was declared under control, while that is in effect; else null."""
    at = f"(to_jsonb({alias}) ->> 'under_control_at')::timestamptz"
    return (
        f"case when {alias}.status::text in ({_LIVE_SQL}) "
        f"and {at} >= coalesce({alias}.alarm_level_set_at, '-infinity'::timestamptz) "
        f"then {at} end"
    )


def _org_of(user_sql: str) -> str:
    return (
        "(select so.name from public.users su "
        "join public.organizations so on so.id = su.primary_org_id "
        f"where su.id = {user_sql})"
    )


def _name_of(user_sql: str) -> str:
    return f"(select su.full_name from public.users su where su.id = {user_sql})"


_DECLARER = "(to_jsonb(a) ->> 'under_control_by')::uuid"
_IN_EFFECT = f"({under_control_at_sql('a')}) is not null"

# For the detail any signed-in person reads (GET /areas/{id}), over areas `a`.
PUBLIC_DETAIL_COLS = f"""
    a.alarm_level_set_at,
    {under_control_at_sql('a')} as under_control_at,
    {_org_of('a.alarm_level_set_by')} as alarm_level_set_by_org,
    case when {_IN_EFFECT} then {_org_of(_DECLARER)} end as under_control_by_org,
    a.resolved_at
"""

# For the staff detail (GET /incidents/{id}): who, as well.
STAFF_DETAIL_COLS = f"""
    {_name_of('a.alarm_level_set_by')} as alarm_level_set_by_name,
    {_org_of('a.alarm_level_set_by')} as alarm_level_set_by_org,
    case when {_IN_EFFECT} then {_name_of(_DECLARER)} end as under_control_by_name,
    case when {_IN_EFFECT} then {_org_of(_DECLARER)} end as under_control_by_org
"""
