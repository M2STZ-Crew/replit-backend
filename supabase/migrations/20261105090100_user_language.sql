-- The language each user reads RepLiT in (5 Nov 2026, issue list 1.5).
--
-- The app offers English or Tagalog (CEFR B1) and tells the server with
-- PUT /auth/me/language, so the alerts a resident gets follow it: the 150 m
-- neighbourhood alert, news on a report they filed, the National ID answer and
-- the test alert (app/services/citizen_copy.py). Staff alerts stay in English.
--
-- Everyone starts on English, the app's default; the app sends the phone's
-- choice at sign-in and whenever it changes.
--
-- Run before deploying the backend that reads it.

alter table public.users
  add column if not exists language text not null default 'en';

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'users_language_check'
  ) then
    alter table public.users
      add constraint users_language_check check (language in ('en', 'tl'));
  end if;
end $$;

comment on column public.users.language is
  'The language the user reads RepLiT in: en (English) or tl (Tagalog). Residents'' alerts and inbox rows use it.';
