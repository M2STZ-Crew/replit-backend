-- The central hub acknowledges under any agency (v1.12.44, 20 November 2026).
--
-- 19 Nov 2026: "there's an unexpected error when the coordinator report a fire
-- incident himself and he acknowledge it by himself too". The error was not the
-- self-report. The central hub (Barangay 76, all in one since 9 Nov 2026) has
-- Fire Volunteer and medical members, and enforce_area_acceptance_org_agency
-- refused any acknowledgement whose organisation is not of the acknowledging
-- agency. The hub is filed under barangay, so its Fire Volunteer and medical
-- members could acknowledge no fire, their own report or anyone's.
--
-- The hub's organisation now counts for every agency, as its Admin already
-- acts for every agency (app/services/access.py). Every other organisation
-- keeps the rule. Until this is applied the backend keeps such an
-- acknowledgement without its organisation (app/services/acknowledge.py), so
-- nothing fails; once it is, the hub is credited with taking part.
--
-- Additive and re-runnable: one function body; no data changes.

create or replace function public.enforce_area_acceptance_org_agency()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.organization_id is not null and not exists (
    select 1 from public.organizations o
    where o.id = new.organization_id
      and (o.agency_type = new.agency or coalesce(o.is_central_hub, false))
  ) then
    raise exception 'organization % does not belong to agency %', new.organization_id, new.agency
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function public.enforce_area_acceptance_org_agency() is
  'An acknowledgement''s organisation must be of its agency, or the central hub, which is every agency (v1.12.44).';
