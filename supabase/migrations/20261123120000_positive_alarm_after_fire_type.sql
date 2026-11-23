-- Positive Fire Alarm after the fire type (23 November 2026, backend v1.12.52).
--
-- "they can't raise an alarm level if someone isn't fill-up the fire type
-- first. and the first one who can fill-up the fire type is the one who comes
-- the incident first"; "before to proceed with positive fire alarm, someone
-- should fill the fire type first".
--
-- Was (20261031090000, 20261109090000): the first verify set Positive Fire
-- Alarm. Now the first fire type sets it, credited to whoever said what is
-- burning, and no alarm level is set on an Area whose fire type is unknown.
-- Who may say what is burning is the API's (app/services/fire_type.py): the
-- first fire team on scene. Areas that already have a level keep it.
--
-- The rest of enforce_alarm_authority is 20261109090000's, unchanged.
-- Re-runnable.

create or replace function public.enforce_alarm_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role       public.user_role;
  v_agency     public.agency_type;
  v_org_agency public.agency_type;
  v_hub        boolean;
  v_changed    boolean;
begin
  -- The first fire type establishes the initial classification. Who may say
  -- it is checked by the API, on this same update.
  if tg_op = 'UPDATE'
     and old.fire_type is null and new.fire_type is not null
     and old.alarm_level is null and new.alarm_level is null
     and new.fire_type_set_by is not null then
    new.alarm_level := 'positive_fire_alarm';
    new.alarm_level_set_by := new.fire_type_set_by;
    new.alarm_level_set_at := now();
    return new;
  end if;

  v_changed := (tg_op = 'INSERT' and new.alarm_level is not null)
            or (tg_op = 'UPDATE' and new.alarm_level is distinct from old.alarm_level);
  if not v_changed then
    return new;
  end if;

  -- No level before somebody on scene says what is burning.
  if new.alarm_level is not null and new.fire_type is null then
    raise exception 'an alarm level needs the fire type first'
      using errcode = 'check_violation';
  end if;

  if new.alarm_level_set_by is null then
    raise exception 'setting alarm_level requires alarm_level_set_by'
      using errcode = 'check_violation';
  end if;

  new.alarm_level_set_at := now();

  select u.role, u.agency_type, o.agency_type, coalesce(o.is_central_hub, false)
    into v_role, v_agency, v_org_agency, v_hub
    from public.users u
    left join public.organizations o on o.id = u.primary_org_id
   where u.id = new.alarm_level_set_by;

  -- BFP sub-admins may set any level.
  if v_role = 'sub_admin' and v_agency = 'bfp' then
    return new;
  end if;

  -- The BFP Admin (an Admin of a BFP organisation) may set any level.
  if v_role = 'admin' and v_org_agency = 'bfp' then
    return new;
  end if;

  -- The central hub's Admin (Barangay 76) does every Admin function, alarm
  -- levels included (9 November 2026).
  if v_role = 'admin' and v_hub then
    return new;
  end if;

  -- Fire Volunteer sub-admins may set ONLY positive_fire_alarm.
  if v_role = 'sub_admin' and v_agency = 'fire_volunteer' then
    if new.alarm_level = 'positive_fire_alarm' then
      return new;
    end if;
    raise exception
      'Fire Volunteers cannot escalate beyond Positive Fire Alarm; % requires BFP (Section 6)',
      new.alarm_level using errcode = 'insufficient_privilege';
  end if;

  raise exception 'only BFP (Coordinator or Admin), the central hub, or Fire Volunteer sub-admins may set alarm levels (Section 6)'
    using errcode = 'insufficient_privilege';
end;
$$;

comment on function public.enforce_alarm_authority() is
  'Defense-in-depth: the first fire type sets Positive Fire Alarm, and no level is set before it; BFP Coordinators, the BFP Admin and the central hub''s Admin set any level; Fire Volunteer Coordinators only Positive Fire Alarm (23 Nov 2026).';
