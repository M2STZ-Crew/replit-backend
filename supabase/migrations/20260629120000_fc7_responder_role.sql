-- ============================================================================
-- FC-7 "Additional Units Needed" is a field request ("Need Backup") — retarget
-- it to response_team so responders can press it from the incident command
-- screen. Sub-admins/admin can still broadcast any code (route-level override).
-- Idempotent.
-- ============================================================================

set search_path = public, extensions;

update public.fire_codes
set target_role = 'response_team'::public.user_role
where code_number = 'FC-7';
