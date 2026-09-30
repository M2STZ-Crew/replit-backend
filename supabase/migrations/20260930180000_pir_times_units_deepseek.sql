-- ============================================================================
-- Post-Incident Report: times and several units; AI summaries by any provider
--
-- The report is now filled entirely by selection (no typing), and records:
--   * when the incident happened and when the fire was out,
--   * every unit that went (a captain may send more than one),
--   * the driver and roster, picked from the organisation's members,
--   * the equipment taken.
--
-- truck_label / truck_type / truck_equipment_id stay: they are NOT NULL, older
-- app builds still send them, and they now hold a readable join of `units` so
-- anything reading the old columns keeps working.
--
-- ai_summaries.anthropic_request_id becomes provider_request_id: summaries are
-- written by DeepSeek now, and the column should not name a vendor.
--
-- Idempotent, so a partially applied deploy can be re-run. No rows are
-- rewritten: post_incident_reports refuses UPDATE by design, and reads fall
-- back to the incident's own timestamps and the truck columns where these are
-- null.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- 1. post_incident_reports: incident time, fire-out time, units
-- ---------------------------------------------------------------------------
alter table public.post_incident_reports
  add column if not exists incident_at timestamptz,
  add column if not exists fire_out_at timestamptz,
  add column if not exists units       jsonb;

comment on column public.post_incident_reports.incident_at is
  'When the incident happened, as the captain confirmed it (defaults to areas.reported_at).';
comment on column public.post_incident_reports.fire_out_at is
  'When the fire was out, as the captain confirmed it (defaults to areas.resolved_at).';
comment on column public.post_incident_reports.units is
  'JSON array of {name, type, equipment_id} - every unit that went.';

alter table public.post_incident_reports
  drop constraint if exists post_incident_reports_units_is_array;
alter table public.post_incident_reports
  add constraint post_incident_reports_units_is_array
    check (units is null
           or (jsonb_typeof(units) = 'array' and jsonb_array_length(units) >= 1));

alter table public.post_incident_reports
  drop constraint if exists post_incident_reports_fire_out_after_incident;
alter table public.post_incident_reports
  add constraint post_incident_reports_fire_out_after_incident
    check (incident_at is null or fire_out_at is null or fire_out_at >= incident_at);

-- ---------------------------------------------------------------------------
-- 2. ai_summaries: the request id is the provider's, whoever that is
-- ---------------------------------------------------------------------------
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'ai_summaries'
      and column_name = 'anthropic_request_id'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'ai_summaries'
      and column_name = 'provider_request_id'
  ) then
    alter table public.ai_summaries
      rename column anthropic_request_id to provider_request_id;
  end if;
end
$$;

comment on column public.ai_summaries.provider_request_id is
  'The AI provider''s id for the request that wrote this summary (DeepSeek completion id).';
