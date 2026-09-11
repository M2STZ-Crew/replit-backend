-- ============================================================================
-- Migration 0021 — Post-Incident Report, Admin routing, observer Accept,
--                  evacuation sites beyond Pasay
-- Master context v10: Section 2.5 (Post-Incident Report lifecycle step),
--                     Section 2.6 (Admin routes; observers Accept),
--                     Section 2.4 (evacuation sites may sit outside Pasay),
--                     Section 4.1 (post_incident_reports).
--
-- Requires 0020 (the two new area_status values) to have been COMMITTED — see
-- the note in that file. Idempotent so a partially applied deploy can be re-run.
--
-- Lifecycle, as the application drives it (app/services/incident.py):
--   arrived --FIRE OUT--> resolved --> post_incident_report --file--> closed
-- The resolve endpoint takes both of the first two steps in one statement, so
-- a resolved area rests in 'post_incident_report' — the "pending report" tray —
-- until its team captain files. Filing is the only way to 'closed', and the
-- trigger in section 4 refuses 'closed' without a filed report.
--
-- Areas already 'resolved' before this migration are left as they are: they
-- were closed out under v9 rules and are history, not paperwork owed.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- 1. areas: timestamps + actor for the two new transitions
-- ---------------------------------------------------------------------------
alter table public.areas
  add column if not exists post_incident_report_at timestamptz,
  add column if not exists closed_at               timestamptz,
  add column if not exists closed_by               uuid references public.users (id)
                                                   on delete set null;

comment on column public.areas.post_incident_report_at is
  'When the area entered the Post-Incident Report step (Section 2.5) — i.e. fire out.';
comment on column public.areas.closed_at is
  'When the Post-Incident Report was filed and the area closed (terminal).';
comment on column public.areas.closed_by is
  'Team captain whose Post-Incident Report closed the area.';

-- Sequencing, mirroring 0008: each step needs the one before it.
alter table public.areas
  drop constraint if exists areas_ts_pir_needs_resolved;
alter table public.areas
  add constraint areas_ts_pir_needs_resolved
    check (post_incident_report_at is null
           or (resolved_at is not null and post_incident_report_at >= resolved_at));

alter table public.areas
  drop constraint if exists areas_ts_closed_needs_pir;
alter table public.areas
  add constraint areas_ts_closed_needs_pir
    check (closed_at is null
           or (post_incident_report_at is not null and closed_at >= post_incident_report_at));

-- ---------------------------------------------------------------------------
-- 2. Lifecycle auto-stamping — extend to the two new statuses
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
      when 'post_incident_report'
                        then new.post_incident_report_at :=
                               coalesce(new.post_incident_report_at, now());
      when 'closed'     then new.closed_at     := coalesce(new.closed_at, now());
      when 'rejected'   then new.rejected_at   := coalesce(new.rejected_at, now());
      when 'merged'     then new.merged_at     := coalesce(new.merged_at, now());
      else null;
    end case;
  end if;
  return new;
end;
$$;
comment on function public.stamp_area_lifecycle() is
  'Auto-stamps the matching lifecycle timestamp when areas.status changes (Section 2.5).';

-- ---------------------------------------------------------------------------
-- 3. Active-incident index — the post-incident step is off the live feed
-- ---------------------------------------------------------------------------
-- Mirrors app.services.incident.active_area_sql() (OFF_FEED_STATUSES). Keep the
-- two in step.
drop index if exists public.areas_active_idx;
create index areas_active_idx on public.areas (reported_at)
  where status not in ('resolved', 'post_incident_report', 'closed', 'rejected', 'merged');

-- ---------------------------------------------------------------------------
-- 4. post_incident_reports (Section 4.1) — one row per closed area
-- ---------------------------------------------------------------------------
create table if not exists public.post_incident_reports (
  id                  uuid primary key default gen_random_uuid(),
  area_id             uuid not null unique references public.areas (id) on delete cascade,

  -- The team captain who filed, plus a snapshot of who they were at the time
  -- (the same reasoning as audit_logs.actor_role: later changes to the account
  -- must not rewrite the record).
  filed_by            uuid references public.users (id) on delete set null,
  filed_by_name       text,
  filed_by_role       public.user_role not null,
  filed_by_agency     public.agency_type not null,
  organization_id     uuid references public.organizations (id) on delete set null,

  -- The unit. truck_equipment_id links a registered truck when there is one;
  -- truck_label is always kept so a borrowed or unregistered unit can be named.
  truck_equipment_id  uuid references public.equipment (id) on delete set null,
  truck_label         text not null check (length(btrim(truck_label)) > 0),
  truck_type          text not null check (length(btrim(truck_type)) > 0),

  driver_name         text not null check (length(btrim(driver_name)) > 0),
  driver_user_id      uuid references public.users (id) on delete set null,

  -- Everyone who went: [{"name": "...", "role": "...", "user_id": "..."|null}, ...]
  roster              jsonb not null
                      check (jsonb_typeof(roster) = 'array' and jsonb_array_length(roster) >= 1),
  equipment_taken     text[] not null check (cardinality(equipment_taken) >= 1),
  notes               text,

  submitted_at        timestamptz not null default now(),
  created_at          timestamptz not null default now()
);
comment on table public.post_incident_reports is
  'Post-Incident Report (Section 2.5): truck, driver, roster and equipment, filed once by the '
  'responding team captain after fire out. Its existence is what permits areas.status = closed.';
comment on column public.post_incident_reports.roster is
  'JSON array of {name, role, user_id} — the full responder roster, filed by the captain.';

create index if not exists post_incident_reports_filed_by_idx
  on public.post_incident_reports (filed_by);
create index if not exists post_incident_reports_submitted_idx
  on public.post_incident_reports (submitted_at);

alter table public.post_incident_reports enable row level security;

-- Single-submit, no draft state (Section 2.5): once filed, the record is fixed.
-- UPDATE is refused for every role, as audit_logs does. DELETE is left to the
-- area cascade (nothing in the application deletes areas).
create or replace function public.post_incident_reports_prevent_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'a Post-Incident Report is fixed once filed; UPDATE is not permitted'
    using errcode = 'P0001';
end;
$$;

drop trigger if exists post_incident_reports_no_update on public.post_incident_reports;
create trigger post_incident_reports_no_update
  before update on public.post_incident_reports
  for each row execute function public.post_incident_reports_prevent_update();

-- No area becomes 'closed' without its record (Section 2.5 submission rule).
-- The application inserts the report and closes the area in one transaction,
-- so the row is visible here by the time the status changes.
create or replace function public.enforce_close_requires_report()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status = 'closed' and new.status is distinct from old.status then
    if not exists (
      select 1 from public.post_incident_reports p where p.area_id = new.id
    ) then
      raise exception
        'an incident cannot be closed until its Post-Incident Report is filed (Section 2.5)'
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end;
$$;
comment on function public.enforce_close_requires_report() is
  'Defense-in-depth: areas.status = closed requires a post_incident_reports row.';

drop trigger if exists enforce_close_requires_report on public.areas;
create trigger enforce_close_requires_report
  before update on public.areas
  for each row execute function public.enforce_close_requires_report();

-- ---------------------------------------------------------------------------
-- 5. area_routes (Section 2.6.2) — Admin routes an area to response agencies
-- ---------------------------------------------------------------------------
-- One row per (area, agency, team). organization_id null means "the whole
-- agency" rather than a particular team. accepted_* is the observer's Accept
-- (Section 2.6.1): an acknowledgement only — it never changes areas.status.
create table if not exists public.area_routes (
  id              uuid primary key default gen_random_uuid(),
  area_id         uuid not null references public.areas (id) on delete cascade,
  agency          public.agency_type not null,
  organization_id uuid references public.organizations (id) on delete cascade,
  routed_by       uuid references public.users (id) on delete set null,
  routed_at       timestamptz not null default now(),
  accepted_by     uuid references public.users (id) on delete set null,
  accepted_at     timestamptz,
  constraint area_routes_unique unique nulls not distinct (area_id, agency, organization_id),
  constraint area_routes_accepted_has_time check (accepted_by is null or accepted_at is not null)
);
comment on table public.area_routes is
  'Admin routing decisions (Section 2.6.2) and observer Accept acknowledgements (Section 2.6.1).';
comment on column public.area_routes.organization_id is
  'The team alerted within the agency; null routes to the agency as a whole.';

create index if not exists area_routes_area_idx on public.area_routes (area_id);
create index if not exists area_routes_agency_idx on public.area_routes (agency, area_id);

alter table public.area_routes enable row level security;

-- A team routed under an agency must belong to that agency.
create or replace function public.enforce_area_route_org_agency()
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

drop trigger if exists enforce_area_route_org_agency on public.area_routes;
create trigger enforce_area_route_org_agency
  before insert or update on public.area_routes
  for each row execute function public.enforce_area_route_org_agency();

-- ---------------------------------------------------------------------------
-- 6. evacuation_sites beyond Pasay (Section 2.4)
-- ---------------------------------------------------------------------------
-- There never was a geometric constraint to lift; what was missing is a way to
-- say where a site is. outside_pasay is generated so a client cannot set it and
-- every surface draws the distinct marker from the same rule.
alter table public.evacuation_sites
  add column if not exists city text not null default 'Pasay City';

alter table public.evacuation_sites
  add column if not exists outside_pasay boolean generated always as (
    regexp_replace(lower(btrim(city)), '\s+city$', '') <> 'pasay'
  ) stored;

comment on column public.evacuation_sites.city is
  'City or municipality the site is in. Sites may sit outside Pasay (Section 2.4).';
comment on column public.evacuation_sites.outside_pasay is
  'Generated: true when city is not Pasay. Drives the distinct map marker.';

-- ---------------------------------------------------------------------------
-- 7. RLS (defense in depth; the API connects as service_role — Section 4.4)
-- ---------------------------------------------------------------------------
drop policy if exists post_incident_reports_select_staff on public.post_incident_reports;
create policy post_incident_reports_select_staff on public.post_incident_reports
  for select to authenticated using ((select public.is_staff()));
drop policy if exists post_incident_reports_admin_all on public.post_incident_reports;
create policy post_incident_reports_admin_all on public.post_incident_reports
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

drop policy if exists area_routes_select_staff on public.area_routes;
create policy area_routes_select_staff on public.area_routes
  for select to authenticated using ((select public.is_staff()));
drop policy if exists area_routes_admin_all on public.area_routes;
create policy area_routes_admin_all on public.area_routes
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));
