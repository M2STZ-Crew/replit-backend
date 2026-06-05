-- ============================================================================
-- Migration 0005 — Dispatch, responder GPS streams, alarms, fire codes
-- Tables: dispatch_logs, responder_locations, alarm_requests, fire_codes,
--         fire_code_events
-- Plus:   ALTER public.areas ADD COLUMN alarm_level
-- Master context: Section 6 (BFP/Fire-Vol authorities), Section 7 (#14-#18),
--                 Section 8 (5 s responder streaming), Section 9 (dispatch
--                 manual/self-select), Phase 13 (fire codes & alarm requests).
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- Enums introduced by this migration
-- ---------------------------------------------------------------------------

-- Full BFP alarm escalation ladder. `positive_fire_alarm` is the maximum a Fire
-- Volunteer sub-admin may set directly; everything above is BFP-exclusive
-- (enforced by the authority CHECK in migration 0008).
create type public.alarm_level as enum (
  'positive_fire_alarm',  -- Fire Volunteer boundary
  'first_alarm',          -- BFP only
  'second_alarm',         -- BFP only
  'third_alarm',          -- BFP only
  'fourth_alarm',         -- BFP only
  'fifth_alarm',          -- BFP only
  'general_alarm'         -- BFP only
);
comment on type public.alarm_level is
  'BFP alarm ladder. Fire Volunteer authority caps at positive_fire_alarm (Section 6).';

create type public.dispatch_type as enum ('manual', 'self_select');
comment on type public.dispatch_type is
  'How a responder ended up assigned to an incident (Section 9).';

create type public.dispatch_status as enum ('active', 'withdrawn', 'completed');
comment on type public.dispatch_status is
  'Lifecycle state of a dispatch assignment.';

-- ---------------------------------------------------------------------------
-- areas.alarm_level — current alarm level on the incident (nullable until set)
-- ---------------------------------------------------------------------------
alter table public.areas
  add column alarm_level public.alarm_level;
comment on column public.areas.alarm_level is
  'Current alarm level on the incident; set/raised via alarm_requests (Phase 13).';

create index areas_alarm_level_idx on public.areas (alarm_level)
  where alarm_level is not null;

-- ---------------------------------------------------------------------------
-- dispatch_logs (Section 7 #14) — assignment of a responder to an incident
-- ---------------------------------------------------------------------------
create table public.dispatch_logs (
  id              uuid primary key default gen_random_uuid(),
  area_id         uuid not null references public.areas (id) on delete cascade,
  responder_id    uuid not null references public.users (id) on delete cascade,
  organization_id uuid references public.organizations (id) on delete set null,
  dispatch_type   public.dispatch_type not null,
  -- For dispatch_type='manual', the sub-admin who issued the assignment.
  -- Required for manual; must be null for self-select.
  dispatched_by   uuid references public.users (id) on delete set null,
  status          public.dispatch_status not null default 'active',
  dispatched_at   timestamptz not null default now(),
  withdrawn_at    timestamptz,
  completed_at    timestamptz,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint dispatch_logs_manual_has_dispatcher check (
    case
      when dispatch_type = 'manual' then dispatched_by is not null
      when dispatch_type = 'self_select' then dispatched_by is null
    end
  )
);
comment on table public.dispatch_logs is
  'Dispatch assignments (manual or self-select) of responders to incident areas.';

create index dispatch_logs_area_idx on public.dispatch_logs (area_id);
create index dispatch_logs_responder_idx on public.dispatch_logs (responder_id);
create index dispatch_logs_org_idx on public.dispatch_logs (organization_id);
create index dispatch_logs_status_idx on public.dispatch_logs (status);
-- A responder can only have ONE active assignment to a given area at a time.
create unique index dispatch_logs_active_uniq
  on public.dispatch_logs (responder_id, area_id)
  where status = 'active';

create trigger set_dispatch_logs_updated_at
  before update on public.dispatch_logs
  for each row execute function public.set_updated_at();

alter table public.dispatch_logs enable row level security;

-- ---------------------------------------------------------------------------
-- responder_locations (Section 7 #15) — live 5 s GPS stream during response
-- ---------------------------------------------------------------------------
create table public.responder_locations (
  id           uuid primary key default gen_random_uuid(),
  responder_id uuid not null references public.users (id) on delete cascade,
  area_id      uuid not null references public.areas (id) on delete cascade,
  dispatch_id  uuid references public.dispatch_logs (id) on delete set null,
  lat          double precision not null check (lat between -90 and 90),
  lng          double precision not null check (lng between -180 and 180),
  location     geography(Point, 4326) generated always as (
                 ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography
               ) stored,
  accuracy_m   double precision,
  speed_mps    double precision check (speed_mps is null or speed_mps >= 0),
  heading_deg  double precision check (heading_deg is null
                  or (heading_deg >= 0 and heading_deg < 360)),
  -- captured_at = device-side timestamp; created_at = server receipt time.
  captured_at  timestamptz not null,
  created_at   timestamptz not null default now()
);
comment on table public.responder_locations is
  'Append-only GPS fixes from responders during active response (5 s cadence, Section 8).';

create index responder_locations_responder_time_idx
  on public.responder_locations (responder_id, captured_at desc);
create index responder_locations_area_time_idx
  on public.responder_locations (area_id, captured_at desc);
create index responder_locations_dispatch_idx on public.responder_locations (dispatch_id);
create index responder_locations_geo_idx on public.responder_locations using gist (location);

alter table public.responder_locations enable row level security;

-- ---------------------------------------------------------------------------
-- alarm_requests (Section 7 #16) — Fire Vol → BFP escalation request
-- ---------------------------------------------------------------------------
create table public.alarm_requests (
  id                      uuid primary key default gen_random_uuid(),
  area_id                 uuid not null references public.areas (id) on delete cascade,
  requested_by            uuid not null references public.users (id) on delete restrict,
  requested_alarm_level   public.alarm_level not null,
  justification           text,
  status                  public.request_status not null default 'pending',
  reviewed_by             uuid references public.users (id) on delete set null,
  reviewed_at             timestamptz,
  review_notes            text,
  -- When BFP actually applied the approved level to public.areas.alarm_level.
  executed_at             timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
comment on table public.alarm_requests is
  'Fire Volunteer -> BFP requests to raise the alarm level on an incident (Section 6, Phase 13).';

create index alarm_requests_area_idx on public.alarm_requests (area_id);
create index alarm_requests_requested_by_idx on public.alarm_requests (requested_by);
create index alarm_requests_status_idx on public.alarm_requests (status);
create index alarm_requests_pending_idx on public.alarm_requests (created_at)
  where status = 'pending';

create trigger set_alarm_requests_updated_at
  before update on public.alarm_requests
  for each row execute function public.set_updated_at();

alter table public.alarm_requests enable row level security;

-- ---------------------------------------------------------------------------
-- fire_codes (Section 7 #17) — code catalog
-- ---------------------------------------------------------------------------
create table public.fire_codes (
  id            uuid primary key default gen_random_uuid(),
  code_number   text not null,
  name          text not null,
  description   text,
  -- Which tier may press this code (sub_admin / response_team / etc.).
  target_role   public.user_role not null,
  -- Optional agency restriction (e.g. BFP-only codes).
  target_agency public.agency_type,
  is_active     boolean not null default true,
  display_order integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint fire_codes_code_number_uniq unique (code_number)
);
comment on table public.fire_codes is
  'Catalog of operational fire codes responders/sub-admins can press; rows seeded in 0011 (Phase 13).';

create index fire_codes_target_role_idx on public.fire_codes (target_role);
create index fire_codes_target_agency_idx on public.fire_codes (target_agency);
create index fire_codes_active_idx on public.fire_codes (display_order) where is_active;

create trigger set_fire_codes_updated_at
  before update on public.fire_codes
  for each row execute function public.set_updated_at();

alter table public.fire_codes enable row level security;

-- ---------------------------------------------------------------------------
-- fire_code_events (Section 7 #18) — per-press log linked to an incident
-- ---------------------------------------------------------------------------
create table public.fire_code_events (
  id           uuid primary key default gen_random_uuid(),
  fire_code_id uuid not null references public.fire_codes (id) on delete restrict,
  area_id      uuid references public.areas (id) on delete set null,
  pressed_by   uuid not null references public.users (id) on delete restrict,
  pressed_at   timestamptz not null default now(),
  notes        text,
  created_at   timestamptz not null default now()
);
comment on table public.fire_code_events is
  'Immutable log of every fire-code press, tied to the incident area where applicable.';

create index fire_code_events_code_idx on public.fire_code_events (fire_code_id);
create index fire_code_events_area_idx on public.fire_code_events (area_id);
create index fire_code_events_pressed_by_idx on public.fire_code_events (pressed_by);
create index fire_code_events_pressed_at_idx on public.fire_code_events (pressed_at);

alter table public.fire_code_events enable row level security;