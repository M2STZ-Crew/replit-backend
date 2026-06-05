-- ============================================================================
-- Migration 0001 — Extensions, enum types, and shared trigger function
-- RepLiT v8 — foundational types used by every later migration.
-- Master context: Section 6 (RBAC tiers), Section 3.3/3.4 (badges, confidence),
-- Section 7 (schema), Section 9 (incident lifecycle).
-- ============================================================================

-- PostGIS lives in the dedicated `extensions` schema (Supabase convention).
-- `if not exists` makes this safe whether PostGIS was already enabled via the
-- dashboard or here. Spatial migrations set `search_path = public, extensions`
-- so the geography type and ST_* functions resolve without schema-qualifying.
create extension if not exists postgis with schema extensions;

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------

-- Four-tier user hierarchy (Section 6). No in-app super admin.
create type public.user_role as enum (
  'admin',
  'sub_admin',
  'response_team',
  'general_user'
);
comment on type public.user_role is
  'Four-tier RBAC hierarchy: admin, sub_admin, response_team, general_user (Section 6).';

-- Agency / organization classification. Distinguishes Fire Volunteer vs BFP vs
-- Barangay/Medical/Police — required for authority rules (BFP-only alarm
-- escalation, Fire-Volunteer-only incident verification).
create type public.agency_type as enum (
  'fire_volunteer',
  'bfp',
  'barangay',
  'medical',
  'police'
);
comment on type public.agency_type is
  'Agency classification for organizations and sub-admin/response-team users.';

-- Progressive verification channels (Section 2, Section 7 #4).
create type public.verification_type as enum (
  'phone',        -- Twilio OTP, +40%
  'email',        -- Brevo link, +10%
  'national_id'   -- Didit.me KYC, +50%
);
comment on type public.verification_type is
  'Verification channel: phone (+40%), email (+10%), national_id KYC (+50%).';

-- Lifecycle status of an individual verification record.
create type public.verification_status as enum (
  'pending',        -- awaiting completion (OTP sent, email sent, KYC submitted)
  'verified',       -- succeeded (auto or admin-approved)
  'manual_review',  -- KYC routed to the admin fallback queue
  'rejected',       -- admin rejected during manual review
  'failed'          -- attempt failed (e.g., wrong OTP, KYC unrecognized)
);
comment on type public.verification_status is
  'Status of a verification attempt; KYC failures route to manual_review (Section 3.2).';

-- Four verification badges driven by verified_percent (Section 3.3).
create type public.verification_badge as enum (
  'yellow',       -- < 50%
  'light_green',  -- 50-89%
  'green',        -- 90-99%
  'green_check'   -- 100%
);
comment on type public.verification_badge is
  'Badge tiers: yellow (<50), light_green (50-89), green (90-99), green_check (100).';

-- Generic approval workflow status (affiliate onboarding, alarm-raise requests,
-- map-layer update requests).
create type public.request_status as enum (
  'pending',
  'approved',
  'rejected'
);
comment on type public.request_status is
  'Generic request approval status used by affiliate, alarm, and map-layer requests.';

-- Incident (area) lifecycle status (Section 9). The seven lifecycle timestamps
-- on the areas table correspond to these transitions.
create type public.area_status as enum (
  'pending',     -- clustered from report(s), awaiting Fire-Volunteer verification
  'verified',    -- verified by a Fire Volunteer sub-admin
  'dispatched',  -- responders assigned (manual or self-select)
  'en_route',    -- responders moving to scene
  'arrived',     -- responders on scene
  'resolved',    -- fire out / incident closed
  'rejected'     -- determined invalid / false report
);
comment on type public.area_status is
  'Incident lifecycle status for clustered areas (Section 9).';

-- Area confidence band derived from the confidence score (Section 3.4).
create type public.confidence_band as enum (
  'high',    -- score >= 0.7  (green)
  'medium',  -- score >= 0.4  (yellow)
  'low'      -- score <  0.4  (red)
);
comment on type public.confidence_band is
  'Confidence band from 0.4*N + 0.3*S + 0.3*V: high>=0.7, medium>=0.4, low<0.4.';

-- ---------------------------------------------------------------------------
-- Shared trigger function: maintain updated_at
-- ---------------------------------------------------------------------------
-- Table-independent (operates only on the NEW row), so it is safe to define
-- before any tables exist. `set search_path = ''` satisfies the Supabase
-- "mutable search_path" advisory; now() resolves from pg_catalog regardless.
-- Attached to tables in later migrations via:
--   create trigger set_<table>_updated_at before update on <table>
--     for each row execute function public.set_updated_at();
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
comment on function public.set_updated_at() is
  'BEFORE UPDATE trigger function that stamps updated_at = now().';