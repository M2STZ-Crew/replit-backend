-- The central hub does everything, all in one (9 November 2026).
--
-- "barangay 76 as a central hub with all admin functions in web (not separated
-- admin, fire, medic, and barangay. it is all in one). and the email of it is
-- barangay76.admin@replit.com". The backend gives the hub's Admin every Admin
-- function on every incident (app/services/access.py, v1.12.26); two things
-- also live in the database:
--
-- 1. Alarm levels. enforce_alarm_authority lets BFP (Coordinators and the BFP
--    Admin) set any level and Fire Volunteer Coordinators only Positive Fire
--    Alarm; now the central hub's Admin sets any level too. Everything else in
--    the function is 20261031090000_positive_alarm_on_verify.sql's.
--
-- 2. Its sign-in. The hub's one Admin signs in as barangay76.admin@replit.com.
--    @replit.com has no mailbox, so the address it had stays as its personal
--    email, where Forgot password? sends the link (routes/password_reset.py
--    send_staff_resets), already confirmed: it was the sign-in. Nothing
--    happens when the hub has no Admin or more than one, or when another
--    account already has the address; a notice says which.
--
-- Run before deploying backend v1.12.26: until then the hub may press Decide on
-- an alarm request and be refused here. Re-runnable.

-- ---------------------------------------------------------------------------
-- 1. The central hub's Admin may set any alarm level
-- ---------------------------------------------------------------------------
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
  'Defense-in-depth: the first verify sets Positive Fire Alarm; BFP Coordinators, the BFP Admin and the central hub''s Admin set any level; Fire Volunteer Coordinators only Positive Fire Alarm (Section 6, PRD v14 §3.4; 9 Nov 2026).';

-- ---------------------------------------------------------------------------
-- 2. The hub's Admin signs in as barangay76.admin@replit.com
-- ---------------------------------------------------------------------------
do $$
declare
  v_address constant text := 'barangay76.admin@replit.com';
  v_admins  integer;
  v_id      uuid;
  v_old     text;
  v_taken   uuid;
begin
  select count(*) into v_admins
    from public.users u
    join public.organizations o on o.id = u.primary_org_id
   where o.is_central_hub and u.role = 'admin';
  if v_admins <> 1 then
    raise notice 'central hub Admins: % (expected 1); sign-in not changed', v_admins;
    return;
  end if;

  select u.id, u.email into v_id, v_old
    from public.users u
    join public.organizations o on o.id = u.primary_org_id
   where o.is_central_hub and u.role = 'admin';

  if lower(coalesce(v_old, '')) = v_address then
    raise notice 'the central hub Admin already signs in as %', v_address;
    return;
  end if;

  select id into v_taken from auth.users where lower(email) = v_address and id <> v_id;
  if v_taken is not null then
    raise notice 'another account (%) has % already; sign-in not changed', v_taken, v_address;
    return;
  end if;

  update auth.users
     set email = v_address,
         email_confirmed_at = coalesce(email_confirmed_at, now()),
         email_change = '',
         email_change_token_new = '',
         raw_user_meta_data = case
           when raw_user_meta_data ? 'email'
             then jsonb_set(raw_user_meta_data, '{email}', to_jsonb(v_address))
           else raw_user_meta_data
         end,
         updated_at = now()
   where id = v_id;

  update auth.identities
     set identity_data = jsonb_set(identity_data, '{email}', to_jsonb(v_address)),
         updated_at = now()
   where user_id = v_id and provider = 'email';

  update public.users
     set email = v_address,
         personal_email = case
           when personal_email is null and v_old is not null
                and lower(v_old) not like '%@replit.com' then lower(v_old)
           else personal_email
         end,
         personal_email_verified_at = case
           when personal_email is null and v_old is not null
                and lower(v_old) not like '%@replit.com' then now()
           else personal_email_verified_at
         end,
         updated_at = now()
   where id = v_id;

  raise notice 'the central hub Admin now signs in as % (was %)', v_address, v_old;
end;
$$;
