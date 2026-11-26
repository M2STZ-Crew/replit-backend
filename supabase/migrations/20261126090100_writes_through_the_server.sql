-- Accounts, organizations and applications change only through the server
-- (26 November 2026, backend v1.12.53; answered "Tighten").
--
-- These policies let any signed-in Admin write the tables directly through
-- the database's own API, past the server's checks (which Admin may change
-- which account or organization). The server uses the service role, which
-- does not read policies, so nothing it does changes. Reading stays as it
-- was: users_select_self_or_staff, organizations_select_all,
-- affiliate_requests_select_own and user_verifications_select_own.
-- Re-runnable.

drop policy if exists users_admin_all on public.users;
drop policy if exists organizations_admin_all on public.organizations;
drop policy if exists affiliate_requests_admin_all on public.affiliate_requests;
drop policy if exists affiliate_requests_insert_self on public.affiliate_requests;
drop policy if exists user_verifications_admin_all on public.user_verifications;
