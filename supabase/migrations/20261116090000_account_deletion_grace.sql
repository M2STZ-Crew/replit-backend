-- v1.12.35: a resident's account is frozen for 30 days before it is deleted.
--
-- 16 Nov 2026: "make the account is in freeze for 30 days before actual
-- deleting it ... (they can still recover it within 30 days)".
--
-- Asking to delete (POST /auth/me/delete, or /auth/delete from the residents'
-- site) stamps deletion_requested_at and freezes the account: it is signed out
-- everywhere, its phones stop getting alerts, and every sign-in and request is
-- refused with the date it goes. POST /auth/restore clears it within the 30
-- days. After them, app/workers/account_deletion.py deletes the account for
-- good (auth.users, and with it public.users and everything that cascades).
--
-- Additive and nullable: safe to apply before or after the backend that reads it.

alter table public.users
  add column if not exists deletion_requested_at timestamptz;

comment on column public.users.deletion_requested_at is
  'When the resident asked for their account to be deleted (null: never, or restored). '
  'Frozen from then; deleted 30 days after unless restored (v1.12.35).';

create index if not exists users_deletion_requested_at_idx
  on public.users (deletion_requested_at)
  where deletion_requested_at is not null;
