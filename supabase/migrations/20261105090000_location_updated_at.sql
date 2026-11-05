-- When each user's last-known location was reported (5 Nov 2026, issue list
-- 2.2: "the citizen was not in the 150m area and yet still got notified").
--
-- The 150 m neighbourhood alert went to everyone whose last-known location was
-- within 150 m of the fire, however old that location was. A phone reports it
-- when the app opens or comes back to the front, so a resident who opened
-- RepLiT at home in the morning was still "next to" their home at night,
-- wherever they were. The worker now counts only a location reported within
-- the last NEIGHBORHOOD_LOCATION_MAX_AGE_MINUTES (30 by default), and this
-- column is when it was reported. The app refreshes it every few minutes while
-- open, and every ~15 minutes while closed for residents who allow location
-- "all the time".
--
-- Existing locations get no time: they count as stale until the phone reports
-- again, which it does the next time the app opens.
--
-- Run before deploying the backend that reads it (app/workers/neighborhood.py).

alter table public.users
  add column if not exists location_updated_at timestamptz;

comment on column public.users.location_updated_at is
  'When latitude/longitude were last reported by the phone. The 150 m neighbourhood alert ignores a location older than NEIGHBORHOOD_LOCATION_MAX_AGE_MINUTES.';

create index if not exists users_location_updated_at_idx
  on public.users (location_updated_at);
