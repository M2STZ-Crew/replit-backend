-- Positive Fire Alarm is what a verified fire starts at (31 Oct 2026, Issue 11).
--
-- It says "this is a real fire", which is what verifying already says, so
-- nobody should have to ask BFP for it. The first verify (reported -> verified)
-- now records it, in the same statement, whoever verified: a Coordinator of any
-- agency, a responder or an Admin. Unverified reports are never classified.
-- Everything above it still goes through POST /alarm-requests and BFP.
--
-- The trigger is the one place that fires for every way into 'verified', and
-- doing it here means the backend needs no change to stay correct, so this can
-- run before or after the deploy. Until it runs a verified Area has no level,
-- as today.
--
-- Also fixes alarm_level_set_at: `coalesce(old value, now())` kept the time of
-- the first level, so with a level now set at verify every later BFP decision
-- would have shown the verify time.
--
-- Areas verified before this keep their record (alarm_level stays null); asking
-- for 1st Alarm works on them as it did. Reversible: re-running the definition
-- in 20261023180000_admin_console_access.sql restores the old behaviour.

create or replace function public.enforce_alarm_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role       public.user_role;
  v_agency     public.agency_type;
  v_org_agency public.agency_type;
  v_changed    boolean;
begin
  -- The first verify establishes the initial classification. Who may verify
  -- is enforce_incident_verification_authority's to check, on this same row.
  if tg_op = 'UPDATE'
     and old.status = 'reported' and new.status = 'verified'
     and new.alarm_level is null and new.verified_by is not null then
    new.alarm_level := 'positive_fire_alarm';
    new.alarm_level_set_by := new.verified_by;
    new.alarm_level_set_at := now();
    return new;
  end if;

  v_changed := (tg_op = 'INSERT' and new.alarm_level is not null)
            or (tg_op = 'UPDATE' and new.alarm_level is distinct from old.alarm_level);
  if not v_changed then
    return new;
  end if;

  if new.alarm_level_set_by is null then
    raise exception 'setting alarm_level requires alarm_level_set_by'
      using errcode = 'check_violation';
  end if;

  new.alarm_level_set_at := now();

  select u.role, u.agency_type, o.agency_type
    into v_role, v_agency, v_org_agency
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

  -- Fire Volunteer sub-admins may set ONLY positive_fire_alarm.
  if v_role = 'sub_admin' and v_agency = 'fire_volunteer' then
    if new.alarm_level = 'positive_fire_alarm' then
      return new;
    end if;
    raise exception
      'Fire Volunteers cannot escalate beyond Positive Fire Alarm; % requires BFP (Section 6)',
      new.alarm_level using errcode = 'insufficient_privilege';
  end if;

  raise exception 'only BFP (Coordinator or Admin) or Fire Volunteer sub-admins may set alarm levels (Section 6)'
    using errcode = 'insufficient_privilege';
end;
$$;

comment on function public.enforce_alarm_authority() is
  'Defense-in-depth: the first verify sets Positive Fire Alarm; BFP Coordinators and the BFP Admin set any level; Fire Volunteer Coordinators only Positive Fire Alarm (Section 6, PRD v14 §3.4).';
