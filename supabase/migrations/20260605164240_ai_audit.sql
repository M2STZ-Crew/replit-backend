-- ============================================================================
-- Migration 0006 — AI summaries & audit logs
-- Tables: ai_summaries, audit_logs
-- Master context: Section 3.6 (Claude Haiku text-only summarization),
--                 Section 7 (#19 ai_summaries, #20 audit_logs),
--                 Phase 11 (token + cost logging), Phase 14 (audit middleware).
-- audit_logs is append-only: trigger-enforced UPDATE/DELETE block (defense in
-- depth) on top of RLS policies (added in 0009).
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- ai_summaries (Section 7 #19) — Claude Haiku text summaries + structured report
-- ---------------------------------------------------------------------------
create table public.ai_summaries (
  id                 uuid primary key default gen_random_uuid(),
  area_id            uuid not null references public.areas (id) on delete cascade,
  -- Model identifier, e.g. "claude-haiku-4-5"
  model              text not null,
  -- Raw prompt sent to the model (for replay/debug; PII-free)
  prompt             text not null,
  -- Token accounting (Phase 11). `cached_tokens` reflects prompt-cache hits.
  prompt_tokens      integer check (prompt_tokens is null or prompt_tokens >= 0),
  completion_tokens  integer check (completion_tokens is null or completion_tokens >= 0),
  cached_tokens      integer check (cached_tokens is null or cached_tokens >= 0),
  total_tokens       integer check (total_tokens is null or total_tokens >= 0),
  cost_usd           numeric(10, 6) check (cost_usd is null or cost_usd >= 0),
  -- Generated artifacts.
  summary_text       text not null,
  structured_report  jsonb,
  -- Anthropic request id (for support escalation).
  anthropic_request_id text,
  generated_at       timestamptz not null default now(),
  created_at         timestamptz not null default now()
);
comment on table public.ai_summaries is
  'Claude Haiku post-incident text summaries + structured fire-out report (Section 3.6). Multiple rows per area allowed — history of regenerations.';
comment on column public.ai_summaries.structured_report is
  'Structured fire-out report: area designation, centroid, the 7 lifecycle timestamps, neighborhood corroboration count, dispatched resources, fire code activations.';

create index ai_summaries_area_idx on public.ai_summaries (area_id, generated_at desc);
create index ai_summaries_generated_idx on public.ai_summaries (generated_at);

alter table public.ai_summaries enable row level security;

-- ---------------------------------------------------------------------------
-- audit_logs (Section 7 #20) — RBAC events, lifecycle transitions, KYC decisions
-- ---------------------------------------------------------------------------
create table public.audit_logs (
  id            uuid primary key default gen_random_uuid(),
  -- Actor identity + snapshot of role/agency at the time of the event.
  actor_user_id uuid references public.users (id) on delete set null,
  actor_role    public.user_role,
  actor_agency  public.agency_type,
  -- Naming convention: "<entity>.<verb>", e.g. "incident.verified",
  -- "alarm.requested", "alarm.executed", "kyc.approved", "kyc.rejected",
  -- "hydrant.override", "map_layer.update_requested", "user.role_changed".
  action        text not null,
  -- Affected entity, e.g. "area" | "user" | "hydrant" | "alarm_request".
  entity_type   text,
  entity_id     uuid,
  -- Denormalized incident link so per-incident audit queries are cheap.
  area_id       uuid references public.areas (id) on delete set null,
  -- Pre/post images for diffable changes (null for purely transactional events).
  before_state  jsonb,
  after_state   jsonb,
  metadata      jsonb not null default '{}'::jsonb,
  -- Request provenance — populated by the FastAPI audit middleware (Phase 14).
  ip_address    inet,
  user_agent    text,
  request_id    text,
  created_at    timestamptz not null default now()
);
comment on table public.audit_logs is
  'Append-only audit trail of RBAC events, incident lifecycle transitions, KYC decisions, and hydrant ground-truth overrides.';
comment on column public.audit_logs.action is
  'Dot-separated event name, e.g. incident.verified, kyc.approved, hydrant.override.';
comment on column public.audit_logs.actor_role is
  'Role of the actor AT THE TIME of the event (snapshot — later role changes do not rewrite history).';

create index audit_logs_actor_idx on public.audit_logs (actor_user_id);
create index audit_logs_action_idx on public.audit_logs (action);
create index audit_logs_entity_idx on public.audit_logs (entity_type, entity_id);
create index audit_logs_area_idx on public.audit_logs (area_id);
create index audit_logs_created_idx on public.audit_logs (created_at);
create index audit_logs_request_idx on public.audit_logs (request_id)
  where request_id is not null;

alter table public.audit_logs enable row level security;

-- Append-only enforcement (defense-in-depth, fires for ALL roles including service_role).
create or replace function public.audit_logs_prevent_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit_logs is append-only; % is not permitted', tg_op
    using errcode = 'P0001';
end;
$$;
comment on function public.audit_logs_prevent_mutation() is
  'Blocks UPDATE/DELETE on audit_logs at the trigger layer — fires for every role.';

create trigger audit_logs_no_update
  before update on public.audit_logs
  for each row execute function public.audit_logs_prevent_mutation();

create trigger audit_logs_no_delete
  before delete on public.audit_logs
  for each row execute function public.audit_logs_prevent_mutation();