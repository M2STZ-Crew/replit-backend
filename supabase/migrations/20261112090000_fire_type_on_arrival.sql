-- What's burning, set on arrival (PRD v14 §4.5.3; 12 November 2026).
--
-- "on arrival the coordinator chooses fire type such as structural fire (refer
-- to figma) (remove the agricultural fire)". The first unit on scene picks one
-- of six types, and a subtype where the type has them (Figma C18 / R08b):
--
--   structural  residential · commercial · industrial   (no agricultural: v14)
--   electrical  high_tension_wire · transformer · entrance_wire · meter
--   vehicular   motorcycle · tricycle · sedan · suv · truck · e_bike · e_car
--   rubbish · grass · chemical (no subtype)
--
-- Checks rather than enums: PRD v14 §6.2 had to drop 'agricultural' from an
-- enum, which Postgres cannot do in place; a check is replaced in one line.
-- POST /incidents/{id}/fire-type writes these (backend v1.12.27). Re-runnable.

alter table public.areas
  add column if not exists fire_type        text,
  add column if not exists fire_subtype     text,
  add column if not exists fire_type_set_by uuid references public.users (id) on delete set null,
  add column if not exists fire_type_set_at timestamptz;

alter table public.areas drop constraint if exists areas_fire_type_check;
alter table public.areas add constraint areas_fire_type_check check (
  fire_type is null
  or fire_type in ('structural', 'electrical', 'vehicular', 'rubbish', 'grass', 'chemical')
);

alter table public.areas drop constraint if exists areas_fire_subtype_check;
alter table public.areas add constraint areas_fire_subtype_check check (
  (fire_type is null and fire_subtype is null)
  or (fire_type = 'structural'
      and fire_subtype in ('residential', 'commercial', 'industrial'))
  or (fire_type = 'electrical'
      and fire_subtype in ('high_tension_wire', 'transformer', 'entrance_wire', 'meter'))
  or (fire_type = 'vehicular'
      and fire_subtype in ('motorcycle', 'tricycle', 'sedan', 'suv', 'truck', 'e_bike', 'e_car'))
  or (fire_type in ('rubbish', 'grass', 'chemical') and fire_subtype is null)
);

comment on column public.areas.fire_type is
  'What is burning, set on arrival (PRD v14 §4.5.3): structural, electrical, vehicular, rubbish, grass or chemical.';
comment on column public.areas.fire_subtype is
  'The fire type''s subtype where it has them (structural, electrical, vehicular); null otherwise. No agricultural (PRD v14).';
