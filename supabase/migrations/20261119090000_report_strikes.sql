-- Prank and malicious reports: strikes, the reporting pause and appeals (v1.12.41).
--
-- 19 Nov 2026: "a false alarm or prank report can be temporarily cannot report
-- and has a progressive penalty that if the user repeats pranking there's a
-- consequence" ("Yes, build it" to the ladder in app/services/report_strikes.py).
--
-- One row per report that staff judged "Prank or malicious". The ladder counts
-- a resident's strikes over 12 months:
--   1st  reporting paused 24 hours, and a lesson on what a false alarm costs
--   2nd  paused 7 days, then 30 days of verify-first
--   3rd  paused 30 days, then 90 days of verify-first   (a second staff member confirms)
--   4th  reporting removed until an appeal is granted    (a second staff member confirms)
--
-- A strike follows the verified mobile number (phone_mac: an HMAC of the E.164
-- number, keyed from the JWT secret) as well as the account, so a new account on
-- the same number keeps it. Nothing else about the person is copied here. A
-- strike is deleted when it expires (12 months after it took effect), and an
-- overturned one 30 days after (app/workers/account_deletion.py, hourly).
--
-- Additive only: the backend before v1.12.41 never reads it.

create table if not exists public.report_strikes (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid references public.users (id) on delete set null,
  phone_mac          text,
  report_id          uuid references public.reports (id) on delete set null,
  area_id            uuid references public.areas (id) on delete set null,
  step               smallint not null check (step between 1 and 4),
  -- What staff found. The resident reads it, so it is written for them.
  reason             text not null check (length(btrim(reason)) between 3 and 500),
  serious            boolean not null default false,
  given_by           uuid references public.users (id) on delete set null,
  given_at           timestamptz not null default now(),
  status             text not null default 'active'
                     check (status in ('awaiting_confirmation', 'active', 'overturned')),
  -- The second staff member's check, for steps 3 and 4 (never the giver).
  checked_by         uuid references public.users (id) on delete set null,
  checked_at         timestamptz,
  check_note         text check (check_note is null or length(check_note) <= 500),
  -- When the pause began: given_at for steps 1 and 2, checked_at for 3 and 4.
  starts_at          timestamptz,
  -- 12 months after starts_at; null for the 4th step (until an appeal) and
  -- while a strike awaits its second check.
  expires_at         timestamptz,
  lesson_seen_at     timestamptz,
  appeal_text        text check (appeal_text is null or length(btrim(appeal_text)) between 10 and 500),
  appealed_at        timestamptz,
  appeal_decision    text check (appeal_decision is null or appeal_decision in ('upheld', 'overturned')),
  appeal_note        text check (appeal_note is null or length(appeal_note) <= 500),
  appeal_decided_by  uuid references public.users (id) on delete set null,
  appeal_decided_at  timestamptz,
  overturned_at      timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint report_strikes_one_per_report unique (report_id),
  constraint report_strikes_active_has_start
    check (status <> 'active' or starts_at is not null),
  constraint report_strikes_overturned_has_time
    check (status <> 'overturned' or overturned_at is not null)
);

comment on table public.report_strikes is
  'Reports staff judged a prank or malicious, and the reporting pause each gives (v1.12.41).';
comment on column public.report_strikes.phone_mac is
  'HMAC-SHA256 of the reporter''s verified E.164 number, so strikes follow the number, not just the account.';
comment on column public.report_strikes.reason is
  'What staff found, as the resident will read it.';

create index if not exists report_strikes_user_idx on public.report_strikes (user_id);
create index if not exists report_strikes_phone_idx on public.report_strikes (phone_mac)
  where phone_mac is not null;
create index if not exists report_strikes_awaiting_idx on public.report_strikes (given_at)
  where status = 'awaiting_confirmation';
create index if not exists report_strikes_appeals_idx on public.report_strikes (appealed_at)
  where appealed_at is not null and appeal_decision is null;

drop trigger if exists set_report_strikes_updated_at on public.report_strikes;
create trigger set_report_strikes_updated_at
  before update on public.report_strikes
  for each row execute function public.set_updated_at();

-- Read and written only by the backend, which connects as the database owner.
alter table public.report_strikes enable row level security;
