"""Post-apply checks for 20260920120000_v11_lifecycle.sql.

Run this on a FRESH connection straight after the migration is applied:

    uv run python supabase/verify_v11_lifecycle.py

Why it is a separate script rather than part of the migration's dry run: the
migration drops and recreates ``public.area_status``. Any database session that
has already planned a statement against ``public.areas`` keeps the old type's
OID in its cache, and the next write fails with

    cache lookup failed for type <oid>
    type of parameter N (public.area_status) does not match that when
    preparing the plan (public.area_status_v10)

That makes the lifecycle impossible to exercise inside the same transaction that
performs the swap, so the structural checks run here instead, against a
connection that never saw the old type.

**The same cache behaviour is the reason the API must be restarted after this
migration**, not merely redeployed — asyncpg pools hold long-lived sessions, and
a connection opened before the swap will fail on its first write afterwards.

Read-only: it asserts, it never writes.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

V11_STATUSES = [
    "reported",
    "verified",
    "en_route",
    "arrived",
    "fire_out",
    "post_incident_report",
    "closed",
    "rejected",
    "merged",
]

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{f' — {detail}' if detail else ''}")


def database_url() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*DATABASE_URL\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL not found in .env")


async def main() -> int:
    import asyncpg

    conn = await asyncpg.connect(database_url(), statement_cache_size=0)
    try:
        print("=== enum (Section 4.3) ===")
        labels = [
            r["enumlabel"]
            for r in await conn.fetch(
                """select enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid
                   where t.typname = 'area_status' order by e.enumsortorder"""
            )
        ]
        check("area_status holds exactly the nine v11 values", labels == V11_STATUSES, str(labels))
        check("'dispatched' is gone", "dispatched" not in labels)
        check("'pending' is gone", "pending" not in labels)
        check("'resolved' is gone", "resolved" not in labels)

        print("\n=== data ===")
        left = await conn.fetchval(
            """select count(*) from public.areas
               where status::text in ('pending','resolved','dispatched')"""
        )
        check("no area left on a v10 status", left == 0, f"{left} remain")
        default = await conn.fetchval(
            """select column_default from information_schema.columns
               where table_schema='public' and table_name='areas' and column_name='status'"""
        )
        check("areas.status defaults to 'reported'", "reported" in (default or ""), str(default))

        print("\n=== constraints (Section 2.5.1) ===")
        names = {
            r["conname"]
            for r in await conn.fetch(
                """select conname from pg_constraint
                   where conrelid = 'public.areas'::regclass and contype = 'c'"""
            )
        }
        check("enroute_needs_verified added", "areas_ts_enroute_needs_verified" in names)
        check("enroute_needs_dispatched removed", "areas_ts_enroute_needs_dispatched" not in names)
        check(
            "dispatched_needs_verified removed",
            "areas_ts_dispatched_needs_verified" not in names,
        )
        check("merged_needs_target rebuilt", "areas_merged_needs_target" in names)

        idx = await conn.fetchval(
            """select indexdef from pg_indexes
               where schemaname='public' and indexname='areas_active_idx'"""
        )
        check("active-feed index rebuilt", idx is not None)
        check("active-feed index uses fire_out", bool(idx) and "fire_out" in idx, str(idx))

        print("\n=== area_acceptances (Section 4.1) ===")
        # to_regclass rather than ::regclass: the latter raises when the table is
        # absent, which would abort the run instead of reporting it as a failure.
        exists = await conn.fetchval("select to_regclass('public.area_acceptances') is not null")
        check("table exists", exists)
        if exists:
            cons = {
                r["conname"]
                for r in await conn.fetch(
                    """select conname from pg_constraint
                       where conrelid = to_regclass('public.area_acceptances')"""
                )
            }
            check("one Accept per actor per Area (idempotency)", "area_acceptances_unique" in cons)
            check(
                "exactly one first-Accept per Area",
                await conn.fetchval(
                    """select exists(select 1 from pg_indexes where schemaname='public'
                       and indexname='area_acceptances_one_first_idx')"""
                ),
            )
            check(
                "RLS enabled",
                await conn.fetchval(
                    """select relrowsecurity from pg_class
                       where oid = to_regclass('public.area_acceptances')"""
                ),
            )
            dupes = await conn.fetchval(
                """select count(*) from (
                     select area_id from public.area_acceptances where is_first
                     group by area_id having count(*) > 1) x"""
            )
            check("no Area has two first-Accepts", dupes == 0, f"{dupes} found")
        else:
            for skipped in (
                "one Accept per actor per Area (idempotency)",
                "exactly one first-Accept per Area",
                "RLS enabled",
                "no Area has two first-Accepts",
            ):
                check(skipped, False, "table missing")

        print("\n=== post_incident_reports (Section 2.5.3) ===")
        cols = {
            r["column_name"]: r
            for r in await conn.fetch(
                """select column_name, is_nullable, column_default from information_schema.columns
                   where table_schema='public' and table_name='post_incident_reports'"""
            )
        }
        check("false_alarm column added", "false_alarm" in cols)
        check("false_alarm_note column added", "false_alarm_note" in cols)
        pir_cons = {
            r["conname"]
            for r in await conn.fetch(
                """select conname from pg_constraint
                   where conrelid = 'public.post_incident_reports'::regclass and contype='c'"""
            )
        }
        check(
            "a flagged report must carry a narrative",
            "post_incident_reports_false_alarm_needs_note" in pir_cons,
        )
        if "false_alarm" in cols and "false_alarm_note" in cols:
            bad = await conn.fetchval(
                """select count(*) from public.post_incident_reports
                   where false_alarm
                     and (false_alarm_note is null or btrim(false_alarm_note) = '')"""
            )
            check("no flagged report lacks its narrative", bad == 0, f"{bad} found")
        else:
            check("no flagged report lacks its narrative", False, "columns missing")

        print("\n=== authority (Section 2.5.1) ===")
        src = await conn.fetchval(
            """select prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace
               where n.nspname='public' and p.proname='enforce_incident_verification_authority'"""
        )
        check("verify no longer pinned to fire_volunteer", "fire_volunteer" not in (src or ""))
        check("verify still limited to admin/sub_admin", "sub_admin" in (src or ""))

        stamp = await conn.fetchval(
            """select prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace
               where n.nspname='public' and p.proname='stamp_area_lifecycle'"""
        )
        check("lifecycle stamping knows fire_out", "fire_out" in (stamp or ""))
        check("lifecycle stamping dropped dispatched", "dispatched" not in (stamp or ""))
    finally:
        await conn.close()

    print(f"\nRESULT: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
