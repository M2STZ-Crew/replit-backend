-- A staff account's personal email (6 Nov 2026).
--
-- Coordinators and responders now sign in with an address made from their
-- name, agency and role (obryan.fircor@replit.com). @replit.com has no
-- mailboxes, so what a password needs goes to the person's own email instead:
-- the welcome link that confirms it and sets the first password, and the
-- Forgot password? link after that (app/services/staff_links.py).
--
-- personal_email_verified_at is set when a link sent to personal_email is
-- opened, and cleared when the address changes.
--
-- Run before deploying the backend that reads it.

alter table public.users
  add column if not exists personal_email text,
  add column if not exists personal_email_verified_at timestamptz;

create index if not exists users_personal_email_lower_idx
  on public.users (lower(personal_email))
  where personal_email is not null;

comment on column public.users.personal_email is
  'The own email of a staff member, where password links go: their sign-in address at @replit.com has no mailbox.';
comment on column public.users.personal_email_verified_at is
  'When a link sent to personal_email was opened; null until then, and again after it changes.';
