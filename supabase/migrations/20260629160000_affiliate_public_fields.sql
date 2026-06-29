-- ============================================================================
-- Public affiliate registration: orgs apply BEFORE they have an account (the
-- web "Affiliation form"). Adds address + a details jsonb (roster, equipment,
-- SEC-cert metadata) so the richer form can be captured. requested_by stays
-- nullable for anonymous submissions. Idempotent.
-- ============================================================================

set search_path = public, extensions;

alter table public.affiliate_requests
  add column if not exists address text,
  add column if not exists details jsonb not null default '{}'::jsonb;
