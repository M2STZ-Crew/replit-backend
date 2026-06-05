-- ============================================================================
-- Migration 0009 — Row Level Security policies (Section 6 RBAC, defense-in-depth)
-- The backend uses service_role (bypasses RLS) as primary enforcement; these
-- policies scope direct `authenticated` access. Writes are mostly service_role/
-- admin; reads are role-scoped. Function calls are wrapped in (select ...) for
-- the Supabase RLS init-plan performance optimization.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- Helper predicates
-- ---------------------------------------------------------------------------
create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = ''
as $$ select coalesce(public.get_my_role() = 'admin', false); $$;
comment on function public.is_admin() is 'True when the current user is an admin.';

create or replace function public.is_staff()
returns boolean
language sql stable security definer set search_path = ''
as $$ select coalesce(public.get_my_role() in
       ('admin','sub_admin','response_team'), false); $$;
comment on function public.is_staff() is
  'True for operational personnel (admin/sub_admin/response_team), false for general_user/anon.';

grant execute on function public.is_admin() to authenticated, anon, service_role;
grant execute on function public.is_staff() to authenticated, anon, service_role;

-- ===========================================================================
-- Reference / broadly-readable tables: SELECT to all authenticated; admin writes
-- ===========================================================================
create policy organizations_select_all on public.organizations
  for select to authenticated using (true);
create policy organizations_admin_all on public.organizations
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy fire_codes_select_all on public.fire_codes
  for select to authenticated using (true);
create policy fire_codes_admin_all on public.fire_codes
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy hydrants_select_all on public.hydrants
  for select to authenticated using (true);
create policy hydrants_admin_all on public.hydrants
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy evacuation_sites_select_all on public.evacuation_sites
  for select to authenticated using (true);
create policy evacuation_sites_admin_all on public.evacuation_sites
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy risk_zones_select_all on public.risk_zones
  for select to authenticated using (true);
create policy risk_zones_admin_all on public.risk_zones
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy bodies_of_water_select_all on public.bodies_of_water
  for select to authenticated using (true);
create policy bodies_of_water_admin_all on public.bodies_of_water
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy underground_cisterns_select_all on public.underground_cisterns
  for select to authenticated using (true);
create policy underground_cisterns_admin_all on public.underground_cisterns
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- ===========================================================================
-- Identity & accounts
-- ===========================================================================
create policy users_select_self_or_staff on public.users
  for select to authenticated
  using (id = (select auth.uid()) or (select public.is_staff()));
create policy users_admin_all on public.users
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy affiliate_requests_select_own on public.affiliate_requests
  for select to authenticated
  using (requested_by = (select auth.uid()) or (select public.is_admin()));
create policy affiliate_requests_insert_self on public.affiliate_requests
  for insert to authenticated with check (requested_by = (select auth.uid()));
create policy affiliate_requests_admin_all on public.affiliate_requests
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy user_verifications_select_own on public.user_verifications
  for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()));
create policy user_verifications_admin_all on public.user_verifications
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- password_reset_tokens: no authenticated policies — service_role only (locked).

create policy org_roster_select on public.org_roster
  for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_staff()));
create policy org_roster_admin_all on public.org_roster
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- ===========================================================================
-- Devices & notifications
-- ===========================================================================
create policy device_tokens_own_all on public.device_tokens
  for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy device_tokens_admin_all on public.device_tokens
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy notification_log_select_own on public.notification_log
  for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()));
create policy notification_log_admin_all on public.notification_log
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- ===========================================================================
-- Incidents, reports, clustering, neighborhood pushes
-- ===========================================================================
create policy areas_select_authenticated on public.areas
  for select to authenticated using (true);
create policy areas_admin_all on public.areas
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy reports_select_own_or_staff on public.reports
  for select to authenticated
  using (reporter_id = (select auth.uid()) or (select public.is_staff()));
create policy reports_admin_all on public.reports
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy area_reports_select_staff on public.area_reports
  for select to authenticated using ((select public.is_staff()));
create policy area_reports_admin_all on public.area_reports
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy area_overlaps_select_staff on public.area_overlaps
  for select to authenticated using ((select public.is_staff()));
create policy area_overlaps_admin_all on public.area_overlaps
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy neighborhood_notifications_select_own on public.neighborhood_notifications
  for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_staff()));
create policy neighborhood_notifications_admin_all on public.neighborhood_notifications
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- ===========================================================================
-- Dispatch, responder streams, alarms, fire codes
-- ===========================================================================
create policy dispatch_logs_select on public.dispatch_logs
  for select to authenticated
  using ((select public.is_staff()) or responder_id = (select auth.uid()));
create policy dispatch_logs_admin_all on public.dispatch_logs
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy responder_locations_select_staff on public.responder_locations
  for select to authenticated
  using ((select public.is_staff()) or responder_id = (select auth.uid()));
create policy responder_locations_admin_all on public.responder_locations
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy alarm_requests_select on public.alarm_requests
  for select to authenticated
  using ((select public.is_staff()) or requested_by = (select auth.uid()));
create policy alarm_requests_admin_all on public.alarm_requests
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy fire_code_events_select_staff on public.fire_code_events
  for select to authenticated using ((select public.is_staff()));
create policy fire_code_events_admin_all on public.fire_code_events
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- ===========================================================================
-- AI summaries & audit logs
-- ===========================================================================
create policy ai_summaries_select_staff on public.ai_summaries
  for select to authenticated using ((select public.is_staff()));
create policy ai_summaries_admin_all on public.ai_summaries
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

-- audit_logs: admin read-only via RLS. Inserts come from service_role; the
-- append-only triggers (0006) block UPDATE/DELETE for every role.
create policy audit_logs_select_admin on public.audit_logs
  for select to authenticated using ((select public.is_admin()));

-- ===========================================================================
-- Equipment & map-layer update requests
-- ===========================================================================
create policy equipment_select_staff on public.equipment
  for select to authenticated using ((select public.is_staff()));
create policy equipment_admin_all on public.equipment
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));

create policy map_layer_requests_select on public.map_layer_update_requests
  for select to authenticated
  using (requested_by = (select auth.uid()) or (select public.is_staff()));
create policy map_layer_requests_insert_self on public.map_layer_update_requests
  for insert to authenticated
  with check (requested_by = (select auth.uid()) and (select public.is_staff()));
create policy map_layer_requests_admin_all on public.map_layer_update_requests
  for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));