-- ============================================================================
-- Migration 0019 — areas: merge accountability columns, constraints, index, trigger
-- Master context: Section 3.4 (Merge vs Keep Separate), Section 4.1 (areas table),
--                 Section 9 (lifecycle timestamps + actor accountability).
--
-- Requires 0018 (the 'merged' enum value) to have been COMMITTED — see the note
-- in that file. Idempotent so a partially applied deploy can be re-run.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- 1. Merge columns — mirrors the verified_/resolved_/rejected_ actor pattern
-- ---------------------------------------------------------------------------
-- merged_into_area_id deliberately has NO on-delete action (matches Section 4.1):
-- ON DELETE SET NULL would fire an UPDATE that violates areas_merged_needs_target
-- below, and NO ACTION keeps the merge chain auditable. Nothing in the application
-- deletes areas, so this never blocks a real operation.
alter table public.areas
  add column if not exists merged_at           timestamptz,
  add column if not exists merged_by           uuid references public.users (id)
                                               on delete set null,
  add column if not exists merged_into_area_id uuid references public.areas (id);

comment on column public.areas.merged_into_area_id is
  'Surviving area this one was merged into (Section 4.1); null unless status = ''merged''.';
comment on column public.areas.merged_by is
  'Dispatcher who chose [Merge] on the overlap review (Section 3.4).';

create index if not exists areas_merged_into_idx
  on public.areas (merged_into_area_id)
  where merged_into_area_id is not null;

-- ---------------------------------------------------------------------------
-- 2. Constraints
-- ---------------------------------------------------------------------------
-- A merged area must name its survivor, and must not name itself.
alter table public.areas
  drop constraint if exists areas_merged_needs_target;
alter table public.areas
  add constraint areas_merged_needs_target
    check (status <> 'merged' or merged_into_area_id is not null);

alter table public.areas
  drop constraint if exists areas_merged_not_self;
alter table public.areas
  add constraint areas_merged_not_self
    check (merged_into_area_id is null or merged_into_area_id <> id);

alter table public.areas
  drop constraint if exists areas_ts_merged_after_reported;
alter table public.areas
  add constraint areas_ts_merged_after_reported
    check (merged_at is null or merged_at >= reported_at);

-- Terminal states are mutually exclusive: an area is resolved, rejected, OR
-- merged — never two. Replaces the two-way check from migration 0008.
alter table public.areas
  drop constraint if exists areas_terminal_exclusive;
alter table public.areas
  add constraint areas_terminal_exclusive
    check (num_nonnulls(resolved_at, rejected_at, merged_at) <= 1);

-- ---------------------------------------------------------------------------
-- 3. Active-incident index — merged areas leave the live feed
-- ---------------------------------------------------------------------------
-- Mirrors app.services.incident.active_area_sql(), which is the application-side
-- source of truth for this predicate. Keep the two in step.
drop index if exists public.areas_active_idx;
create index areas_active_idx on public.areas (reported_at)
  where status not in ('resolved', 'rejected', 'merged');

-- ---------------------------------------------------------------------------
-- 4. Lifecycle auto-stamping — extend to merged_at
-- ---------------------------------------------------------------------------
create or replace function public.stamp_area_lifecycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and new.status is distinct from old.status then
    case new.status
      when 'verified'   then new.verified_at   := coalesce(new.verified_at, now());
      when 'dispatched' then new.dispatched_at := coalesce(new.dispatched_at, now());
      when 'en_route'   then new.en_route_at   := coalesce(new.en_route_at, now());
      when 'arrived'    then new.arrived_at    := coalesce(new.arrived_at, now());
      when 'resolved'   then new.resolved_at   := coalesce(new.resolved_at, now());
      when 'rejected'   then new.rejected_at   := coalesce(new.rejected_at, now());
      when 'merged'     then new.merged_at     := coalesce(new.merged_at, now());
      else null;
    end case;
  end if;
  return new;
end;
$$;
comment on function public.stamp_area_lifecycle() is
  'Auto-stamps the matching lifecycle timestamp when areas.status changes (Section 9).';

-- ---------------------------------------------------------------------------
-- 5. Backfill historical merges
-- ---------------------------------------------------------------------------
-- Areas previously absorbed by [Merge] were written as rejected/'merged'. Restate
-- them as status 'merged' and recover the survivor + actor from the overlap row
-- that recorded the decision. Only rows whose surviving area is still identifiable
-- are converted (the NOT NULL join) — areas_merged_needs_target would reject the
-- rest, and leaving them as rejected is the safe, auditable outcome.
-- DISTINCT ON keeps one row per area: an area could historically appear in more
-- than one merged pair, and UPDATE ... FROM would otherwise pick arbitrarily.
with restated as (
  select distinct on (a.id)
         a.id                                          as area_id,
         case when o.area_a_id = a.id then o.area_b_id
              else o.area_a_id end                     as survivor_id,
         o.decided_by,
         coalesce(o.decided_at, a.rejected_at)         as decided_at
  from public.areas a
  join public.area_overlaps o
    on o.decision = 'merge'
   and (o.area_a_id = a.id or o.area_b_id = a.id)
  where a.status = 'rejected'
    and a.rejection_reason = 'merged'
  order by a.id, o.decided_at desc nulls last
)
update public.areas a
   set status              = 'merged',
       merged_into_area_id = r.survivor_id,
       merged_by           = r.decided_by,
       merged_at           = r.decided_at,
       rejected_at         = null,
       rejected_by         = null,
       rejection_reason    = null
  from restated r
 where a.id = r.area_id
   and r.survivor_id is not null
   and r.survivor_id <> a.id;
