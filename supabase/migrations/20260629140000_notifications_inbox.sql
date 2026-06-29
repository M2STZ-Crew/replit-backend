-- ============================================================================
-- In-app notification inbox: one row per recipient per event, so users see a
-- history of their alerts (fire alerts, incident updates, dispatches, alarm
-- requests) inside the app — complementing the ephemeral FCM push. Idempotent.
-- ============================================================================

set search_path = public, extensions;

create table if not exists public.notifications (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users (id) on delete cascade,
  type       text not null,            -- fire_alert | incident_update | responder_dispatch | alarm_request | ...
  title      text not null,
  body       text not null,
  data       jsonb not null default '{}'::jsonb,
  is_read    boolean not null default false,
  created_at timestamptz not null default now()
);

comment on table public.notifications is
  'Per-user in-app notification inbox; mirrors the FCM pushes so users keep a history.';

create index if not exists notifications_user_created_idx
  on public.notifications (user_id, created_at desc);
create index if not exists notifications_user_unread_idx
  on public.notifications (user_id) where is_read = false;

alter table public.notifications enable row level security;
