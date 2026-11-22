"""A frozen organization in SQL (v1.12.51).

A suspended or revoked affiliate is frozen: nobody of it signs in or acts
(app/api/routes/affiliate_standing.py, v1.12.28). The API refused them, but
the socket still opened and alerts still went to their phones. Whoever picks
who is alerted adds :func:`not_frozen_sql`.
"""

from __future__ import annotations

FROZEN = ("suspended", "revoked")


def not_frozen_sql(user: str = "u") -> str:
    """A condition true unless the ``user`` row's organization is frozen.

    Read through to_jsonb: without migration 20261112120000 nobody is.
    """
    standings = ", ".join(f"'{standing}'" for standing in FROZEN)
    return (
        "not exists (select 1 from public.organizations frozen_org "
        f"where frozen_org.id = {user}.primary_org_id "
        f"and to_jsonb(frozen_org) ->> 'standing' in ({standings}))"
    )
