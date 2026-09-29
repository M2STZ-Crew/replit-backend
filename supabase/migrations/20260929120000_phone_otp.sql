-- ===========================================================================
-- Phone verification by SMS through Semaphore
-- ===========================================================================
-- Phone verification (+40%, Section 2.1) moves from Twilio Verify, a trial
-- account that never delivered, to Semaphore. It also becomes the gate a
-- citizen account must pass before it can use the app.
--
-- Semaphore only sends; the backend now owns every code. Two things follow.

-- ---------------------------------------------------------------------------
-- 1. A ledger of every code sent
-- ---------------------------------------------------------------------------
-- Each SMS costs two Semaphore credits and the OTP route has no rate limit of
-- its own. The per-account limit alone does not protect a victim's phone —
-- ten throwaway accounts would buy ten times the texts to one number — so the
-- per-number limit has to count across accounts, and has to survive a restart.
-- It is also the record of what the credit was spent on.
create table if not exists public.phone_otp_sends (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references public.users (id) on delete cascade,
  phone               text not null,
  sent_at             timestamptz not null default now(),
  provider_message_id text,
  constraint phone_otp_sends_phone_e164 check (phone ~ '^\+639[0-9]{9}$')
);

comment on table public.phone_otp_sends is
  'One row per verification SMS sent through Semaphore. Drives the per-account and '
  'per-number send limits; service role only.';

create index if not exists phone_otp_sends_phone_idx
  on public.phone_otp_sends (phone, sent_at desc);
create index if not exists phone_otp_sends_user_idx
  on public.phone_otp_sends (user_id, sent_at desc);

-- No policies: only the API, as the service role, reads or writes this table.
alter table public.phone_otp_sends enable row level security;

-- ---------------------------------------------------------------------------
-- 2. One verified account per phone number
-- ---------------------------------------------------------------------------
-- users.phone was never unique, so one number could verify any number of
-- accounts — which defeats a gate whose purpose is to make fake accounts
-- expensive. The API refuses a number another account has verified, with a
-- message that says so; this index is the guarantee underneath it, so two
-- accounts verifying the same number at the same moment cannot both succeed.
--
-- Partial on phone_verified: an unverified number typed in and abandoned claims
-- nothing. No account has ever verified a phone, so nothing existing conflicts.
create unique index if not exists users_verified_phone_unique
  on public.users (phone)
  where phone_verified and phone is not null;
