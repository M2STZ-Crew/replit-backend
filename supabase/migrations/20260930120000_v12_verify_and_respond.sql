-- ===========================================================================
-- v12: verifying and responding are separate acts (Master Context v12 §2.5)
-- ===========================================================================
-- v11 collapsed "this is a real fire" and "we are going" into one Accept, and
-- only a team captain (or Admin) could press it. In an emergency the captain
-- may be away from the phone, asleep, or on another fire, so v12:
--
--   * lets any response team member verify, as well as captains and Admin;
--   * moves the incident to en_route only when someone actually responds
--     (the API does that; no schema change is needed for it — dispatch_logs
--     already holds who is responding, and its partial unique index already
--     stops anyone responding to the same incident twice).
--
-- The one thing the database itself refuses today is a responder verifying:
-- enforce_incident_verification_authority pins verified_by to admin or
-- sub_admin. It widens here to include response_team. Citizens stay out, and
-- verified_by stays mandatory.
--
-- Reversible: re-running the v11 definition of this function restores the old
-- pin. No data changes.

create or replace function public.enforce_incident_verification_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role public.user_role;
begin
  if not (
       (tg_op = 'INSERT' and (new.status = 'verified' or new.verified_by is not null))
    or (tg_op = 'UPDATE' and (new.status = 'verified'
        or new.verified_by is distinct from old.verified_by))
  ) then
    return new;
  end if;

  if new.status = 'verified' and new.verified_by is null then
    raise exception 'incident verification requires verified_by (the verifying staff member)'
      using errcode = 'check_violation';
  end if;

  if new.verified_by is not null then
    select role into v_role from public.users where id = new.verified_by;

    if v_role is distinct from 'admin'
       and v_role is distinct from 'sub_admin'
       and v_role is distinct from 'response_team' then
      raise exception
        'only a responder, a team captain or Admin may verify incidents (v12 Section 2.5.1)'
        using errcode = 'insufficient_privilege';
    end if;
  end if;

  return new;
end;
$$;

comment on function public.enforce_incident_verification_authority() is
  'Defence-in-depth: verifying is limited to admin, sub_admin and response_team (v12 Section 2.5.1).';
