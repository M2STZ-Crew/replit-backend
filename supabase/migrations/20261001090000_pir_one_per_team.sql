-- ============================================================================
-- Post-Incident Report: one per responding team, not one per incident
--
-- A fire is often fought by more than one team. Until now an incident could
-- hold exactly one Post-Incident Report (UNIQUE area_id), so whichever captain
-- filed first closed it and the other teams' units, crews and equipment were
-- never recorded.
--
-- Now each team files its own: one report per organisation per incident. A
-- captain with no organisation on their account files for themselves.
--
-- What does not change:
--   * the first report filed is still what closes the incident (the trigger
--     enforce_close_requires_report only asks that a report exists);
--   * a filed report still cannot be edited (post_incident_reports_no_update).
--
-- Idempotent. No rows are changed.
-- ============================================================================

set search_path = public, extensions;

alter table public.post_incident_reports
  drop constraint if exists post_incident_reports_area_id_key;

-- One report per team per incident. coalesce: a captain whose account has no
-- organisation is their own "team", so two such captains can both file.
create unique index if not exists post_incident_reports_one_per_team_idx
  on public.post_incident_reports (area_id, coalesce(organization_id, filed_by));

-- The UNIQUE constraint was also the lookup index for "this incident's reports".
create index if not exists post_incident_reports_area_idx
  on public.post_incident_reports (area_id);

comment on table public.post_incident_reports is
  'Post-Incident Report (Section 2.5): times, units, driver, roster and equipment, filed once '
  'per responding team by its captain after fire out. The first one filed is what permits '
  'areas.status = closed; later ones add the other teams'' records to the same incident.';
