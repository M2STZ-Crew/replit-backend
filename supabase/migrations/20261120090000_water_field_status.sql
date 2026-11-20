-- Water resources from the field (v1.12.43).
--
-- 19 Nov 2026, the user's answers on water resources: after checking a
-- hydrant on site, Fire Volunteer and BFP coordinators and responders set its
-- status, "working, low pressure, broken, or no access, with who checked and
-- when"; residents see where water is, never its status.
--
-- Working is 'operational' and broken is 'non_operational', as before. These
-- two are new. Who checked and when are the hydrant's ground_truth_by and
-- ground_truth_at, as before.
--
-- A body of water can be switched off and kept on record, as hydrants and
-- cisterns already are ("Mark it gone or unusable so it leaves everyone's map
-- (kept on record, not deleted)").
--
-- Additive only: two enum values and one column with a default. The backend
-- before v1.12.43 reads neither.

alter type public.hydrant_status add value if not exists 'low_pressure';
alter type public.hydrant_status add value if not exists 'no_access';

alter table public.bodies_of_water
  add column if not exists is_active boolean not null default true;

comment on column public.bodies_of_water.is_active is
  'False when switched off: off every map but the editor''s, kept on record (v1.12.43).';
