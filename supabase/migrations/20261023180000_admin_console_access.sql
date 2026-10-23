-- ============================================================================
-- One Admin console, one Admin per organisation (PRD v13/v14 §4.6; REPLIT
-- (MAIN) pass 6, A00 "Four permission variants")
--
-- Until now every Admin account was the system owner: it had no organisation
-- and could do everything. v13/v14 give each affiliate its own Admin (BFP
-- Pasay and PNP Pasay are singletons), all in the one console, with what each
-- may do decided by its organisation:
--
--   * every Admin sees every active incident, and acknowledges the ones its
--     agency was asked for;
--   * the Barangay 76 central hub also reviews affiliates and National IDs —
--     and nothing more ("Nothing here makes the central hub a superuser");
--   * the BFP Admin sets the alarm level (PRD v14 §3.4: "only authority
--     allowed to execute alarm escalation").
--
-- An organisation Admin is still role 'admin' with no agency of its own
-- (users_agency_consistency); its agency is its organisation's. The API reads
-- both columns below; until this runs it treats no organisation as the hub and
-- refuses a BFP Admin's alarm level with a clear message.
--
-- Additive and idempotent. An Admin with no organisation keeps everything it
-- had.
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- 1. The central hub
-- ---------------------------------------------------------------------------
alter table public.organizations
  add column if not exists is_central_hub boolean not null default false;

comment on column public.organizations.is_central_hub is
  'The one central-hub organisation (Barangay 76, PRD v14 §16.1). Its Admins also review affiliate applications and National IDs.';

-- There is one hub.
create unique index if not exists organizations_one_central_hub_idx
  on public.organizations (is_central_hub)
  where is_central_hub;

-- Barangay 76, if its organisation is already on the network. The accounts
-- script sets it otherwise.
update public.organizations
   set is_central_hub = true
 where id = (
         select id from public.organizations
          where name = 'Barangay 76 Zone 10 Pasay'
            and agency_type = 'barangay'
            and is_active
          order by created_at
          limit 1
       )
   and not exists (select 1 from public.organizations where is_central_hub);

-- ---------------------------------------------------------------------------
-- 2. A BFP Admin may set the alarm level
-- ---------------------------------------------------------------------------
-- Same rule as before for Coordinators: BFP sets any level, a Fire Volunteer
-- Coordinator only Positive Fire Alarm. New: an Admin whose organisation is
-- BFP sets any level.
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
  v_changed := (tg_op = 'INSERT' and new.alarm_level is not null)
            or (tg_op = 'UPDATE' and new.alarm_level is distinct from old.alarm_level);
  if not v_changed then
    return new;
  end if;

  if new.alarm_level_set_by is null then
    raise exception 'setting alarm_level requires alarm_level_set_by'
      using errcode = 'check_violation';
  end if;

  new.alarm_level_set_at := coalesce(new.alarm_level_set_at, now());

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
  'Defense-in-depth: BFP Coordinators and the BFP Admin set any alarm level; Fire Volunteer Coordinators only Positive Fire Alarm (Section 6, PRD v14 §3.4).';
