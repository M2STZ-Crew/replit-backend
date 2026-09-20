-- ===========================================================================
-- v11 lifecycle (Master Context v11 Sections 2.5, 4.1, 4.3)
-- ===========================================================================
-- v11 collapses verify-then-dispatch into a single Accept. The two-step made
-- responders wait for a coordinator to be free before they could roll; from
-- here the first Accept carries the Area from `reported` straight through
-- `verified` to `en_route`, and the choice of truck and roster moves out of the
-- live incident into the Post-Incident Report (Section 2.5.3).
--
-- What that costs at the schema level, in order:
--
--   1. Two CHECK constraints encode the dispatch step. `enroute_needs_
--      dispatched` in particular would reject every v11 Accept, because an
--      Accept reaches en_route without ever stamping dispatched_at.
--   2. The `dispatched` enum value has to go (Section 4.3 lists the nine v11
--      values and dispatched is not among them). Postgres cannot drop an enum
--      value in place, so the type is rebuilt and the column rewritten.
--   3. `stamp_area_lifecycle` stamps a timestamp per status and names the old
--      labels.
--   4. `enforce_incident_verification_authority` pins verification to a Fire
--      Volunteer sub-admin. In v11 Accept *is* the verify act and Admin,
--      Coordinators and Observers may all press it (Section 2.5.1), so the
--      database pin has to widen or every Accept fails beneath the API.
--
-- Column names are deliberately left alone. `resolved_at` keeps its name even
-- though the status it records is now `fire_out`, and `dispatched_at` stays as
-- a vestigial column: renaming them would ripple into the API response schemas
-- (PostIncidentReportResponse.resolved_at) for no behavioural gain. The status
-- vocabulary is what v11 renames; the timestamp columns are internal.
--
-- `dispatch_logs` and `area_routes` are retained but no longer written by v11
-- code paths (Section 4.1). They are dropped by a follow-up migration once no
-- code reads them — not here, so that this migration stays reversible.

-- ---------------------------------------------------------------------------
-- 1. Retire the dispatch-step constraints
-- ---------------------------------------------------------------------------
-- Dropped before the data move below, because the areas currently sitting in
-- `dispatched` are about to become `en_route` and the old constraint insists
-- en_route_at may only exist once dispatched_at does.
alter table public.areas drop constraint if exists areas_ts_dispatched_needs_verified;
alter table public.areas drop constraint if exists areas_ts_enroute_needs_dispatched;

-- Two more objects bake the enum into their own definition, and Postgres cannot
-- rewrite the column underneath them: the partial index that defines the active
-- feed, and the merged-needs-target CHECK. Both are dropped here and rebuilt in
-- step 4 against the v11 vocabulary. (Found by dry-running this migration: the
-- rewrite fails with "operator does not exist: area_status <> area_status_v10"
-- while either one still stands.)
drop index if exists public.areas_active_idx;
alter table public.areas drop constraint if exists areas_merged_needs_target;

-- ---------------------------------------------------------------------------
-- 2. Move incidents out of the step that is being removed
-- ---------------------------------------------------------------------------
-- An Area in `dispatched` had responders assigned and was waiting to roll,
-- which is exactly where a v11 Accept would have left it: en_route. The
-- lifecycle trigger stamps en_route_at on the way through.
update public.areas
   set status = 'en_route'
 where status = 'dispatched';

-- ---------------------------------------------------------------------------
-- 3. Rebuild area_status without `dispatched` (Section 4.3)
-- ---------------------------------------------------------------------------
-- `pending` becomes `reported` and `resolved` becomes `fire_out`: the operator-
-- facing names Section 2.5 uses. Only areas.status is typed area_status, so the
-- rewrite touches one column.
alter type public.area_status rename to area_status_v10;

create type public.area_status as enum (
  'reported',             -- clustered from report(s), nobody has accepted yet
  'verified',             -- an Accept landed; held only momentarily in practice
  'en_route',             -- responders moving to scene (first Accept lands here)
  'arrived',              -- responders on scene
  'fire_out',             -- the fire is out; the paperwork is still owed
  'post_incident_report', -- waiting on the team captain to file
  'closed',               -- terminal: filed and done
  'rejected',             -- terminal: determined invalid / false report
  'merged'                -- terminal: absorbed into a surviving area
);

comment on type public.area_status is
  'Incident lifecycle status for clustered areas (v11 Section 2.5).';

alter table public.areas alter column status drop default;

alter table public.areas
  alter column status type public.area_status
  using (
    case status::text
      when 'pending'    then 'reported'
      when 'resolved'   then 'fire_out'
      when 'dispatched' then 'en_route'   -- defensive: step 2 emptied this
      else status::text
    end
  )::public.area_status;

alter table public.areas alter column status set default 'reported';

drop type public.area_status_v10;

-- ---------------------------------------------------------------------------
-- 4. The ordering rule that replaces enroute_needs_dispatched
-- ---------------------------------------------------------------------------
-- En route still may not precede verification — the Accept sets both in one
-- transaction, so verified_at is always present and never later.
alter table public.areas
  add constraint areas_ts_enroute_needs_verified
  check (
    en_route_at is null
    or (verified_at is not null and en_route_at >= verified_at)
  );

-- Rebuilt from step 1, now against the v11 type.
alter table public.areas
  add constraint areas_merged_needs_target
  check (status <> 'merged' or merged_into_area_id is not null);

-- The active feed, mirroring OFF_FEED_STATUSES in app/services/incident.py:
-- fire out ends the response, but the incident stays off the feed while the
-- paperwork is owed, so a new report near a fire that is out but not yet closed
-- opens its own Area instead of being swallowed by the old one.
create index areas_active_idx on public.areas (reported_at)
  where status <> all (array[
    'fire_out'::public.area_status,
    'post_incident_report'::public.area_status,
    'closed'::public.area_status,
    'rejected'::public.area_status,
    'merged'::public.area_status
  ]);

-- ---------------------------------------------------------------------------
-- 5. Lifecycle timestamps for the v11 vocabulary
-- ---------------------------------------------------------------------------
create or replace function public.stamp_area_lifecycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and new.status is distinct from old.status then
    case new.status
      when 'verified'   then new.verified_at := coalesce(new.verified_at, now());
      when 'en_route'   then new.en_route_at := coalesce(new.en_route_at, now());
      when 'arrived'    then new.arrived_at  := coalesce(new.arrived_at, now());
      -- resolved_at keeps its column name; the status it records is fire_out.
      when 'fire_out'   then new.resolved_at := coalesce(new.resolved_at, now());
      when 'post_incident_report'
                        then new.post_incident_report_at :=
                               coalesce(new.post_incident_report_at, now());
      when 'closed'     then new.closed_at   := coalesce(new.closed_at, now());
      when 'rejected'   then new.rejected_at := coalesce(new.rejected_at, now());
      when 'merged'     then new.merged_at   := coalesce(new.merged_at, now());
      else null;
    end case;
  end if;
  return new;
end;
$$;

comment on function public.stamp_area_lifecycle() is
  'Auto-stamps the matching lifecycle timestamp when areas.status changes (v11 Section 2.5).';

-- ---------------------------------------------------------------------------
-- 6. Who may verify, widened to who may Accept (Section 2.5.1)
-- ---------------------------------------------------------------------------
-- v9 and v10 pinned verification to a Fire Volunteer sub-admin. In v11 Accept
-- is the verify act and it is available to Admin, Coordinator sub-admins
-- (fire_volunteer, bfp) and Observer sub-admins (police, medical, barangay)
-- alike — first to Accept wins. The pin therefore widens to "staff", which is
-- still defence in depth: a response_team member or a citizen cannot verify,
-- and verified_by remains mandatory.
--
-- Reject stays coordinator-only, but that has always been enforced in the API
-- (assert_coordinator) rather than here, so there is nothing to change for it.
create or replace function public.enforce_incident_verification_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role public.user_role;
begin
  if not (
       (tg_op = 'INSERT' and (new.status = 'verified' or new.verified_by is not null))
    or (tg_op = 'UPDATE' and (new.status = 'verified'
        or new.verified_by is distinct from old.verified_by))
  ) then
    return new;
  end if;

  if new.status = 'verified' and new.verified_by is null then
    raise exception 'incident verification requires verified_by (the accepting staff member)'
      using errcode = 'check_violation';
  end if;

  if new.verified_by is not null then
    select role into v_role from public.users where id = new.verified_by;

    if v_role is distinct from 'admin' and v_role is distinct from 'sub_admin' then
      raise exception
        'only an admin or a sub-admin may accept incidents (v11 Section 2.5.1)'
        using errcode = 'insufficient_privilege';
    end if;
  end if;

  return new;
end;
$$;

comment on function public.enforce_incident_verification_authority() is
  'Defence-in-depth: Accept (the v11 verify act) is limited to admin and sub_admin (Section 2.5.1).';

-- ---------------------------------------------------------------------------
-- 7. False alarm on the Post-Incident Report (Section 2.5.3)
-- ---------------------------------------------------------------------------
-- A team that reaches `arrived` and finds nothing — a prank, a fire already
-- out, the wrong address — still owes a report. The flag records that, and the
-- narrative is required so "false alarm" is never an unexplained checkbox.
alter table public.post_incident_reports
  add column if not exists false_alarm      boolean not null default false,
  add column if not exists false_alarm_note text;

alter table public.post_incident_reports
  drop constraint if exists post_incident_reports_false_alarm_needs_note;

alter table public.post_incident_reports
  add constraint post_incident_reports_false_alarm_needs_note
  check (
    not false_alarm
    or (false_alarm_note is not null and length(btrim(false_alarm_note)) > 0)
  );

comment on column public.post_incident_reports.false_alarm is
  'Set when the team arrived and found nothing (v11 Section 2.5.3). Requires a narrative.';
comment on column public.post_incident_reports.false_alarm_note is
  'Why the call was a false alarm. Mandatory whenever false_alarm is true.';

-- ---------------------------------------------------------------------------
-- 8. area_acceptances (Section 4.1)
-- ---------------------------------------------------------------------------
-- One row per Accept per Area. The first row is the one that moved the Area to
-- verified and en_route; every later row is a participating agency saying "we
-- are on it too", which is logged but changes no status (Section 2.5.1).
--
-- Unique on (area_id, user_id) makes Accept idempotent for the same actor, as
-- Section 11.1 requires. A partial unique index guarantees exactly one first
-- Accept per Area, so the race between two agencies is settled by the database
-- rather than by whichever transaction happens to commit second.
-- `agency` is nullable on purpose: Admin accounts carry no agency_type, and
-- Section 2.6.2 keeps an Admin Accept as the safety net for when no agency has
-- picked an Area up. A null agency therefore reads as "Admin, for the system".
create table if not exists public.area_acceptances (
  id              uuid primary key default gen_random_uuid(),
  area_id         uuid not null references public.areas (id) on delete cascade,
  user_id         uuid not null references public.users (id) on delete cascade,
  agency          public.agency_type,
  organization_id uuid references public.organizations (id) on delete set null,
  is_first        boolean not null default false,
  accepted_at     timestamptz not null default now(),
  constraint area_acceptances_unique unique (area_id, user_id),
  -- A team only means something under an agency.
  constraint area_acceptances_org_needs_agency
    check (organization_id is null or agency is not null)
);

comment on table public.area_acceptances is
  'One row per Accept per Area (v11 Section 4.1); is_first marks the verifying Accept.';

create index if not exists area_acceptances_area_idx
  on public.area_acceptances (area_id);
create index if not exists area_acceptances_agency_idx
  on public.area_acceptances (agency, area_id);

create unique index if not exists area_acceptances_one_first_idx
  on public.area_acceptances (area_id) where is_first;

alter table public.area_acceptances enable row level security;

drop policy if exists area_acceptances_select_staff on public.area_acceptances;
create policy area_acceptances_select_staff on public.area_acceptances
  for select to authenticated using ((select public.is_staff()));
drop policy if exists area_acceptances_admin_all on public.area_acceptances;
create policy area_acceptances_admin_all on public.area_acceptances
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- A team accepting under an agency must belong to that agency — the same rule
-- area_routes enforces, for the same reason.
create or replace function public.enforce_area_acceptance_org_agency()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.organization_id is not null and not exists (
    select 1 from public.organizations o
    where o.id = new.organization_id and o.agency_type = new.agency
  ) then
    raise exception 'organization % does not belong to agency %', new.organization_id, new.agency
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists enforce_area_acceptance_org_agency on public.area_acceptances;
create trigger enforce_area_acceptance_org_agency
  before insert or update on public.area_acceptances
  for each row execute function public.enforce_area_acceptance_org_agency();

-- ---------------------------------------------------------------------------
-- 9. Carry the v10 Accept acknowledgements forward
-- ---------------------------------------------------------------------------
-- area_routes.accepted_* recorded the v10 observer Accept. Those presses were
-- real and belong in the new ledger, marked is_first = false: under v10 an
-- Accept never moved the status, so none of them was a verifying Accept.
insert into public.area_acceptances (area_id, user_id, agency, organization_id, is_first, accepted_at)
select r.area_id, r.accepted_by, r.agency, r.organization_id, false, r.accepted_at
  from public.area_routes r
 where r.accepted_by is not null
   and r.accepted_at is not null
on conflict (area_id, user_id) do nothing;

-- ---------------------------------------------------------------------------
-- 10. Mark what v11 stops writing
-- ---------------------------------------------------------------------------
-- Kept so this migration stays reversible and so the history of live incidents
-- is not lost. A follow-up migration drops both once no code path reads them
-- (Section 10.3, Section 12.1 item 9).
comment on table public.dispatch_logs is
  'v11: retained for history; the dispatch step is gone. Still written by self-dispatch '
  'as a responder-to-incident association only — it no longer moves areas.status.';
comment on table public.area_routes is
  'v11: retained for history. Admin no longer routes (Section 2.6.2) and Accept now '
  'writes public.area_acceptances. Nothing writes this table.';
