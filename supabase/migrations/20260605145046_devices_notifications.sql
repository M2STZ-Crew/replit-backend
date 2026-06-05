-- ============================================================================
-- Migration 0003 — Device tokens & notification log
-- Tables: device_tokens, notification_log
-- Master context: Section 7 (#6 device_tokens, #7 notification_log),
--                 Section 3.5 (neighborhood pushes), Phases 5 / 8 / 9.
-- RLS enabled per table (deny-all until policies are added in 0009).
-- ============================================================================

set search_path = public, extensions;

-- Enum: client platform for an FCM device token
create type public.device_platform as enum ('android', 'ios', 'web');
comment on type public.device_platform is 'Client platform for an FCM device token.';

-- Enum: notification category (for the lifecycle delivery audit)
create type public.notification_type as enum (
  'neighborhood_alert',  -- 300 m crowdsourced validation push (Section 3.5)
  'incident_status',     -- incident lifecycle change (Section 9)
  'dispatch',            -- responder dispatch
  'alarm',               -- alarm escalation
  'verification',        -- verification / KYC result
  'system'               -- generic system message
);
comment on type public.notification_type is 'Category of an outbound push notification.';

-- Enum: push delivery status
create type public.notification_status as enum ('pending', 'sent', 'failed');
comment on type public.notification_status is 'Delivery state of a logged push notification.';

-- ---------------------------------------------------------------------------
-- device_tokens (Section 7 #6) — multiple FCM tokens per user
-- ---------------------------------------------------------------------------
create table public.device_tokens (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users (id) on delete cascade,
  fcm_token    text not null,
  platform     public.device_platform not null,
  device_id    text,
  device_name  text,
  app_version  text,
  is_active    boolean not null default true,
  last_used_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint device_tokens_fcm_token_uniq unique (fcm_token)
);
comment on table public.device_tokens is
  'FCM registration tokens; a user may have several (one per device). Unique per token.';

create index device_tokens_user_idx on public.device_tokens (user_id);
create index device_tokens_active_idx on public.device_tokens (user_id) where is_active;

create trigger set_device_tokens_updated_at
  before update on public.device_tokens
  for each row execute function public.set_updated_at();

alter table public.device_tokens enable row level security;

-- ---------------------------------------------------------------------------
-- notification_log (Section 7 #7) — lifecycle push delivery audit
-- ---------------------------------------------------------------------------
create table public.notification_log (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid references public.users (id) on delete set null,
  device_token_id uuid references public.device_tokens (id) on delete set null,
  type            public.notification_type not null,
  status          public.notification_status not null default 'pending',
  title           text,
  body            text,
  data            jsonb not null default '{}'::jsonb,
  -- area_id links a push to an incident area. The FK to public.areas is added in
  -- migration 0004 (areas is created there); kept as a plain column here.
  area_id         uuid,
  fcm_message_id  text,
  error           text,
  sent_at         timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
comment on table public.notification_log is
  'Audit trail of outbound push notifications and their delivery outcome (Section 7 #7).';

create index notification_log_user_idx on public.notification_log (user_id);
create index notification_log_type_idx on public.notification_log (type);
create index notification_log_status_idx on public.notification_log (status);
create index notification_log_area_idx on public.notification_log (area_id);
create index notification_log_created_idx on public.notification_log (created_at);

create trigger set_notification_log_updated_at
  before update on public.notification_log
  for each row execute function public.set_updated_at();

alter table public.notification_log enable row level security;