-- ============================================================================
-- Responder accounts made by coordinators (v1.12.4)
--
-- A coordinator (any sub_admin: Fire Volunteer, BFP, police, medical,
-- barangay) creates the Response Team accounts of their own agency and team,
-- names them by the account directory's rule (jdelacruz.resfir@replit.com),
-- resets their passwords, and deactivates or reactivates them.
--
-- Deactivating keeps the account and everything it did (dispatches, GPS,
-- reports, audit) and only stops it signing in: the API refuses an inactive
-- account on every request and the socket, and Supabase Auth bans it so no
-- new session can be made.
--
-- Additive and idempotent. Every existing account stays active.
-- ============================================================================

set search_path = public, extensions;

alter table public.users
  add column if not exists is_active boolean not null default true;

alter table public.users
  add column if not exists deactivated_at timestamptz;

alter table public.users
  add column if not exists deactivated_by uuid references public.users (id) on delete set null;

-- Who made the account, when a coordinator did (null for self-signup, Admin
-- and accounts from before this).
alter table public.users
  add column if not exists created_by uuid references public.users (id) on delete set null;

comment on column public.users.is_active is
  'False once a coordinator (or Admin) deactivates the account: it keeps its history but cannot sign in.';
comment on column public.users.created_by is
  'The coordinator who created this account (Response Team accounts made from the coordinator console).';

-- A coordinator's roster: responders of one agency, by team.
create index if not exists users_staff_roster_idx
  on public.users (agency_type, primary_org_id)
  where role = 'response_team';
