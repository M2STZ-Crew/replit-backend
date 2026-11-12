-- An affiliate organisation's standing: active, suspended or revoked
-- (12 November 2026, backend v1.12.28).
--
-- "affiliate management (freeze account, or soft delete, or hard delete, for
-- revoked reasons)". Answered: all three, each with a reason, audited.
--
--   suspended  frozen: nobody of the organisation signs in or acts; Restore
--              undoes it at any time.
--   revoked    removed from the network (a soft delete): frozen as above, its
--              records kept; Restore undoes it for 30 days.
--   (delete)   permanently, only an organisation with no incidents on record;
--              there is no row left to hold a standing.
--
-- The reason is one of: misconduct, inactive, duplicate,
-- fraudulent_application, organization_request, other. Re-runnable.

alter table public.organizations
  add column if not exists standing            text not null default 'active',
  add column if not exists standing_reason     text,
  add column if not exists standing_note       text,
  add column if not exists standing_changed_at timestamptz,
  add column if not exists standing_changed_by uuid references public.users (id) on delete set null;

alter table public.organizations drop constraint if exists organizations_standing_check;
alter table public.organizations add constraint organizations_standing_check
  check (standing in ('active', 'suspended', 'revoked'));

alter table public.organizations drop constraint if exists organizations_standing_reason_check;
alter table public.organizations add constraint organizations_standing_reason_check
  check (
    standing_reason is null
    or standing_reason in (
      'misconduct', 'inactive', 'duplicate', 'fraudulent_application',
      'organization_request', 'other'
    )
  );

comment on column public.organizations.standing is
  'active, suspended (frozen; restorable any time) or revoked (soft-deleted; restorable for 30 days). Backend v1.12.28.';
comment on column public.organizations.standing_reason is
  'Why it was suspended or revoked: misconduct, inactive, duplicate, fraudulent_application, organization_request, other.';
