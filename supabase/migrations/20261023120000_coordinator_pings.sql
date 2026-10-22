-- ============================================================================
-- Coordinator reminder pings (v1.12.9, PRD v14 §4.13.2)
--
-- A coordinator who does not open a new-fire push is reminded: vibrate only
-- at +2 min, their agency's sound at +5, vibrate only at +7, the sound at
-- +10, then nothing more (app/workers/coordinator_pings.py). One row per
-- coordinator per Area holds where that cycle is.
--
-- It stops early when they open the incident (POST /incidents/{id}/seen),
-- when their agency acknowledges it, or when it leaves the live feed.
--
-- Additive and idempotent. Only the backend (service_role) reads or writes
-- it, so RLS is on with no policies.
-- ============================================================================

set search_path = public, extensions;

create table if not exists public.coordinator_pings (
  area_id     uuid not null references public.areas (id) on delete cascade,
  user_id     uuid not null references public.users (id) on delete cascade,
  started_at  timestamptz not null default now(),
  -- Reminders sent after the first push (0 to 4).
  step        smallint not null default 0 check (step between 0 and 4),
  stopped_at  timestamptz,
  stop_reason text check (stop_reason in ('opened', 'acknowledged', 'closed', 'done')),
  primary key (area_id, user_id)
);

comment on table public.coordinator_pings is
  'A coordinator''s reminder cycle for a new fire they have not opened (PRD v14 §4.13.2).';

-- The worker reads only the cycles still running.
create index if not exists coordinator_pings_running_idx
  on public.coordinator_pings (started_at)
  where stopped_at is null;

alter table public.coordinator_pings enable row level security;
