-- Citizen profile fields collected at signup and editable in the app
-- (mobile / date of birth / gender). Additive and idempotent.

alter table public.users
  add column if not exists mobile        text,
  add column if not exists date_of_birth date,
  add column if not exists gender        text;

comment on column public.users.mobile is
  'Contact mobile number entered at signup (unverified; distinct from the OTP-verified phone).';
comment on column public.users.date_of_birth is 'Citizen date of birth (profile).';
comment on column public.users.gender is 'Citizen gender (free text; profile).';
