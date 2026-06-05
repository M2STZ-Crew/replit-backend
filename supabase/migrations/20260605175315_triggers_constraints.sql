-- ============================================================================
-- Migration 0008 — Triggers, functions & constraints (behavior + defense-in-depth)
-- Master context: Section 6 (BFP-only escalation, Fire-Vol-only verification),
--                 Section 9 (7 lifecycle timestamps + sequencing),
--                 Section 3.3 (verified_percent -> badge), Phase 3 (signup).
-- ============================================================================

set search_path = public, extensions;

-- ===========================================================================
-- 1. areas: extra actor columns + lifecycle sequencing CHECK constraints
-- ===========================================================================
alter table public.areas
  add column alarm_level_set_by uuid references public.users (id) on delete set null,
  add column alarm_level_set_at timestamptz;
comment on column public.areas.alarm_level_set_by is
  'User who set the current alarm_level; authority validated by enforce_alarm_authority.';

alter table public.areas
  add constraint areas_ts_verified_after_reported
    check (verified_at is null or verified_at >= reported_at),
  add constraint areas_ts_dispatched_needs_verified
    check (dispatched_at is null
           or (verified_at is not null and dispatched_at >= verified_at)),
  add constraint areas_ts_enroute_needs_dispatched
    check (en_route_at is null
           or (dispatched_at is not null and en_route_at >= dispatched_at)),
  add constraint areas_ts_arrived_needs_enroute
    check (arrived_at is null
           or (en_route_at is not null and arrived_at >= en_route_at)),
  add constraint areas_ts_resolved_after_reported
    check (resolved_at is null or resolved_at >= reported_at),
  add constraint areas_ts_rejected_after_reported
    check (rejected_at is null or rejected_at >= reported_at),
  add constraint areas_terminal_exclusive
    check (not (resolved_at is not null and rejected_at is not null));

-- ===========================================================================
-- 2. Role helper functions (SECURITY DEFINER; used by RLS in 0009)
-- ===========================================================================
create or replace function public.get_my_role()
returns public.user_role
language sql
stable
security definer
set search_path = ''
as $$
  select role from public.users where id = auth.uid();
$$;
comment on function public.get_my_role() is
  'Current user''s role from public.users (SECURITY DEFINER bypasses RLS to avoid recursion).';

create or replace function public.get_my_agency()
returns public.agency_type
language sql
stable
security definer
set search_path = ''
as $$
  select agency_type from public.users where id = auth.uid();
$$;
comment on function public.get_my_agency() is
  'Current user''s agency_type from public.users (SECURITY DEFINER).';

grant execute on function public.get_my_role() to authenticated, anon, service_role;
grant execute on function public.get_my_agency() to authenticated, anon, service_role;

-- ===========================================================================
-- 3. handle_new_user() — provision public.users on auth signup
-- ===========================================================================
-- SECURITY: role is ALWAYS 'general_user' here. Elevation to sub_admin/
-- response_team/admin happens only via admin (service_role) action — never from
-- user-supplied signup metadata.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.users (id, email, phone, full_name, role)
  values (
    new.id,
    new.email,
    new.phone,
    coalesce(new.raw_user_meta_data ->> 'full_name',
             new.raw_user_meta_data ->> 'name'),
    'general_user'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
comment on function public.handle_new_user() is
  'AFTER INSERT on auth.users: creates the matching public.users row as general_user.';

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ===========================================================================
-- 4. Incident verification authority (Fire-Volunteer-only; BFP cannot verify)
-- ===========================================================================
create or replace function public.enforce_incident_verification_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role   public.user_role;
  v_agency public.agency_type;
  v_check  boolean;
begin
  v_check := (tg_op = 'INSERT' and (new.status = 'verified' or new.verified_by is not null))
          or (tg_op = 'UPDATE' and (new.status = 'verified'
              or new.verified_by is distinct from old.verified_by));
  if not v_check then
    return new;
  end if;

  if new.status = 'verified' and new.verified_by is null then
    raise exception 'incident verification requires verified_by (a Fire Volunteer sub-admin)'
      using errcode = 'check_violation';
  end if;

  if new.verified_by is not null then
    select role, agency_type into v_role, v_agency
    from public.users where id = new.verified_by;

    if v_role is distinct from 'sub_admin' or v_agency is distinct from 'fire_volunteer' then
      raise exception
        'only a Fire Volunteer sub-admin may verify incidents; BFP cannot verify (Section 6)'
        using errcode = 'insufficient_privilege';
    end if;
  end if;

  return new;
end;
$$;
comment on function public.enforce_incident_verification_authority() is
  'Defense-in-depth: incident verification restricted to Fire Volunteer sub-admins (Section 6).';

drop trigger if exists enforce_verification_authority on public.areas;
create trigger enforce_verification_authority
  before insert or update on public.areas
  for each row execute function public.enforce_incident_verification_authority();

-- ===========================================================================
-- 5. Alarm escalation authority (Fire-Vol <= positive_fire_alarm; BFP any)
-- ===========================================================================
create or replace function public.enforce_alarm_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_role   public.user_role;
  v_agency public.agency_type;
  v_changed boolean;
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

  select role, agency_type into v_role, v_agency
  from public.users where id = new.alarm_level_set_by;

  -- BFP sub-admins may set any level.
  if v_role = 'sub_admin' and v_agency = 'bfp' then
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

  raise exception 'only BFP or Fire Volunteer sub-admins may set alarm levels (Section 6)'
    using errcode = 'insufficient_privilege';
end;
$$;
comment on function public.enforce_alarm_authority() is
  'Defense-in-depth: BFP-exclusive alarm escalation; Fire Vol capped at positive_fire_alarm (Section 6).';

drop trigger if exists enforce_alarm_authority on public.areas;
create trigger enforce_alarm_authority
  before insert or update on public.areas
  for each row execute function public.enforce_alarm_authority();

-- ===========================================================================
-- 6. Lifecycle auto-stamping (status change -> matching *_at timestamp)
-- ===========================================================================
create or replace function public.stamp_area_lifecycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and new.status is distinct from old.status then
    case new.status
      when 'verified'   then new.verified_at   := coalesce(new.verified_at, now());
      when 'dispatched' then new.dispatched_at := coalesce(new.dispatched_at, now());
      when 'en_route'   then new.en_route_at   := coalesce(new.en_route_at, now());
      when 'arrived'    then new.arrived_at    := coalesce(new.arrived_at, now());
      when 'resolved'   then new.resolved_at   := coalesce(new.resolved_at, now());
      when 'rejected'   then new.rejected_at   := coalesce(new.rejected_at, now());
      else null;
    end case;
  end if;
  return new;
end;
$$;
comment on function public.stamp_area_lifecycle() is
  'Auto-stamps the matching lifecycle timestamp when areas.status changes (Section 9).';

drop trigger if exists stamp_area_lifecycle_ts on public.areas;
create trigger stamp_area_lifecycle_ts
  before update on public.areas
  for each row execute function public.stamp_area_lifecycle();

-- ===========================================================================
-- 7. Recompute users.verified_percent from the user_verifications ledger
-- ===========================================================================
create or replace function public.recompute_user_verification()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := coalesce(new.user_id, old.user_id);
  v_percent integer;
begin
  select least(100, coalesce(sum(percent_awarded), 0))
  into v_percent
  from public.user_verifications
  where user_id = v_user_id and status = 'verified';

  update public.users u
  set
    verified_percent = v_percent,
    phone_verified = exists (
      select 1 from public.user_verifications
      where user_id = v_user_id and type = 'phone' and status = 'verified'),
    email_verified = exists (
      select 1 from public.user_verifications
      where user_id = v_user_id and type = 'email' and status = 'verified'),
    id_verified = exists (
      select 1 from public.user_verifications
      where user_id = v_user_id and type = 'national_id' and status = 'verified')
  where u.id = v_user_id;

  return coalesce(new, old);
end;
$$;
comment on function public.recompute_user_verification() is
  'Recomputes users.verified_percent and channel flags (drives the generated badge) from user_verifications.';

drop trigger if exists recompute_user_verification_aiud on public.user_verifications;
create trigger recompute_user_verification_aiud
  after insert or update or delete on public.user_verifications
  for each row execute function public.recompute_user_verification();