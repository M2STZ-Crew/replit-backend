-- ============================================================================
-- Migration 0002 — Identity & organizations
-- Tables: organizations, affiliate_requests, users, user_verifications,
--         password_reset_tokens, org_roster
-- Master context: Section 2, Section 6 (RBAC), Section 7 (#1,#2,#3,#4,#5,#8),
--                 Section 3.3 (badges), Section 3.5 (300 m user proximity).
-- RLS is enabled per table here (deny-all until policies are added in 0009).
-- search_path includes `extensions` so geography/ST_* resolve unqualified.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- organizations (Section 7 #1)
-- ---------------------------------------------------------------------------
create table public.organizations (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  agency_type   public.agency_type not null,
  description   text,
  contact_email text,
  contact_phone text,
  address       text,
  latitude      double precision,
  longitude     double precision,
  location      geography(Point, 4326) generated always as (
                  case
                    when latitude is not null and longitude is not null
                    then ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                    else null
                  end
                ) stored,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.organizations is
  'Affiliate organizations (Fire Volunteer, BFP, Medical, Police, Barangay).';

create index organizations_agency_type_idx on public.organizations (agency_type);
create index organizations_location_idx on public.organizations using gist (location);

create trigger set_organizations_updated_at
  before update on public.organizations
  for each row execute function public.set_updated_at();

alter table public.organizations enable row level security;

-- ---------------------------------------------------------------------------
-- users (Section 7 #3) — one row per auth.users, across all four tiers
-- ---------------------------------------------------------------------------
create table public.users (
  id               uuid primary key references auth.users (id) on delete cascade,
  role             public.user_role not null default 'general_user',
  agency_type      public.agency_type,
  primary_org_id   uuid references public.organizations (id) on delete set null,
  full_name        text,
  email            text,
  phone            text,
  verified_percent integer not null default 0 check (verified_percent between 0 and 100),
  phone_verified   boolean not null default false,
  email_verified   boolean not null default false,
  id_verified      boolean not null default false,
  badge            public.verification_badge generated always as (
                     case
                       when verified_percent >= 100 then 'green_check'::public.verification_badge
                       when verified_percent >= 90  then 'green'::public.verification_badge
                       when verified_percent >= 50  then 'light_green'::public.verification_badge
                       else 'yellow'::public.verification_badge
                     end
                   ) stored,
  latitude         double precision,
  longitude        double precision,
  location         geography(Point, 4326) generated always as (
                     case
                       when latitude is not null and longitude is not null
                       then ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                       else null
                     end
                   ) stored,
  last_active_at   timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint users_agency_consistency check (
    case
      when role in ('sub_admin', 'response_team') then agency_type is not null
      else agency_type is null
    end
  )
);
comment on table public.users is
  'All users across the four tiers; mirrors auth.users. Holds verified_percent and last-known location for 300 m neighborhood queries (Section 3.5).';
comment on column public.users.badge is
  'Auto-derived verification badge from verified_percent (Section 3.3).';
comment on column public.users.location is
  'Auto-derived geography(Point,4326) from latitude/longitude; GIST-indexed for ST_DWithin.';

create index users_role_idx on public.users (role);
create index users_agency_type_idx on public.users (agency_type);
create index users_primary_org_idx on public.users (primary_org_id);
create index users_location_idx on public.users using gist (location);

create trigger set_users_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

alter table public.users enable row level security;

-- ---------------------------------------------------------------------------
-- affiliate_requests (Section 7 #2) — organization onboarding workflow
-- ---------------------------------------------------------------------------
create table public.affiliate_requests (
  id                uuid primary key default gen_random_uuid(),
  organization_name text not null,
  agency_type       public.agency_type not null,
  requested_by      uuid references public.users (id) on delete set null,
  contact_name      text,
  contact_email     text,
  contact_phone     text,
  message           text,
  status            public.request_status not null default 'pending',
  organization_id   uuid references public.organizations (id) on delete set null,
  reviewed_by       uuid references public.users (id) on delete set null,
  reviewed_at       timestamptz,
  review_notes      text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
comment on table public.affiliate_requests is
  'Pending/approved/rejected organization onboarding requests; links to the created organization on approval.';

create index affiliate_requests_status_idx on public.affiliate_requests (status);
create index affiliate_requests_requested_by_idx on public.affiliate_requests (requested_by);

create trigger set_affiliate_requests_updated_at
  before update on public.affiliate_requests
  for each row execute function public.set_updated_at();

alter table public.affiliate_requests enable row level security;

-- ---------------------------------------------------------------------------
-- user_verifications (Section 7 #4) — one row per channel per user
-- ---------------------------------------------------------------------------
create table public.user_verifications (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.users (id) on delete cascade,
  type               public.verification_type not null,
  status             public.verification_status not null default 'pending',
  percent_awarded    integer not null default 0 check (percent_awarded between 0 and 100),
  provider           text,
  provider_reference text,
  metadata           jsonb not null default '{}'::jsonb,
  submitted_at       timestamptz not null default now(),
  verified_at        timestamptz,
  reviewed_by        uuid references public.users (id) on delete set null,
  reviewed_at        timestamptz,
  review_notes       text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint user_verifications_user_type_uniq unique (user_id, type)
);
comment on table public.user_verifications is
  'Phone (+40%), email (+10%), and national_id KYC (+50%) verification records (Sections 2, 3.2, 3.3).';

create index user_verifications_user_idx on public.user_verifications (user_id);
create index user_verifications_status_idx on public.user_verifications (status);
-- Admin manual-review queue (KYC fallback, Section 3.2)
create index user_verifications_manual_review_idx
  on public.user_verifications (submitted_at)
  where status = 'manual_review';

create trigger set_user_verifications_updated_at
  before update on public.user_verifications
  for each row execute function public.set_updated_at();

alter table public.user_verifications enable row level security;

-- ---------------------------------------------------------------------------
-- password_reset_tokens (Section 7 #5) — OTP-based password reset
-- ---------------------------------------------------------------------------
create table public.password_reset_tokens (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users (id) on delete cascade,
  token_hash text not null,
  expires_at timestamptz not null,
  used_at    timestamptz,
  created_at timestamptz not null default now()
);
comment on table public.password_reset_tokens is
  'Hashed OTP password-reset tokens (plaintext OTP is never stored).';
comment on column public.password_reset_tokens.token_hash is
  'SHA-256 hash of the one-time code; verification re-hashes the submitted code.';

create index password_reset_tokens_user_idx on public.password_reset_tokens (user_id);
create index password_reset_tokens_expires_idx on public.password_reset_tokens (expires_at);

alter table public.password_reset_tokens enable row level security;

-- ---------------------------------------------------------------------------
-- org_roster (Section 7 #8) — user membership in organizations
-- ---------------------------------------------------------------------------
create table public.org_roster (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id         uuid not null references public.users (id) on delete cascade,
  member_role     public.user_role not null default 'response_team',
  title           text,
  is_active       boolean not null default true,
  joined_at       timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint org_roster_org_user_uniq unique (organization_id, user_id)
);
comment on table public.org_roster is
  'Membership of users in organizations with their assigned role within that org.';

create index org_roster_user_idx on public.org_roster (user_id);
create index org_roster_org_idx on public.org_roster (organization_id);

create trigger set_org_roster_updated_at
  before update on public.org_roster
  for each row execute function public.set_updated_at();

alter table public.org_roster enable row level security;