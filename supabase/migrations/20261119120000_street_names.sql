-- Fires named after their streets (v1.12.42, 18 Nov 2026: "instead of area,
-- it will be called 'Near [street]' or the street itself because 'Area #1' is
-- not appropriate ... '[street] corner [street]' or 'near [street]'";
-- answered "Corner, else Near", and the area number "Nowhere on screen").
--
-- public.streets: Metro Manila's named streets from OpenStreetMap (ODbL; see
-- docs/data-sources.md), loaded by scripts/load_streets.py and read when a
-- new Area is named (app/services/place_names.py). The lines are kept in UTM
-- zone 51N (EPSG:32651), so distances are metres on a plane, exact enough
-- across Metro Manila, and the GiST index answers "what is near" quickly.
--
-- areas.designation now holds the name every screen and alert shows ("Taft
-- Avenue corner Gil Puyat Avenue", "Near F. Victor Street", "Near F. Victor
-- Street (2)"); the number ("Area 3.2") moves to areas.area_code, kept for
-- the exported PDF report. place_street, place_cross and place_number are
-- the name's parts.
--
-- Additive: the backend before v1.12.42 neither reads nor writes the new
-- columns, so this can be applied before it is replaced.

create table if not exists public.streets (
  id      bigint generated always as identity primary key,
  osm_id  bigint not null,
  name    text not null,
  kind    text not null,
  geom    extensions.geometry(LineString, 32651) not null
);

create unique index if not exists streets_osm_id_key on public.streets (osm_id);
create index if not exists streets_geom_gist on public.streets using gist (geom);

-- Read by the server only.
alter table public.streets enable row level security;

comment on table public.streets is
  'Metro Manila''s named streets from OpenStreetMap (ODbL), one row per way, '
  'in EPSG:32651. Names new Areas (app/services/place_names.py).';
comment on column public.streets.osm_id is 'The OpenStreetMap way id.';
comment on column public.streets.kind is 'The way''s highway tag: residential, primary ...';

alter table public.areas
  add column if not exists area_code    text,
  add column if not exists place_street text,
  add column if not exists place_cross  text,
  add column if not exists place_number integer check (place_number is null or place_number >= 2);

comment on column public.areas.designation is
  'The name every screen and alert shows: "Taft Avenue corner Gil Puyat Avenue", '
  '"Near F. Victor Street", "Near F. Victor Street (2)", or its coordinates when no '
  'street is near (v1.12.42). Before v1.12.42 it was the number, now area_code.';
comment on column public.areas.area_code is
  'The Area number ("Area 3", "Area 3.2"): the PDF report''s reference only, never shown '
  'on screen (v1.12.42).';
comment on column public.areas.place_street is
  'The street the name is about: the nearer street at a corner, else the nearest street.';
comment on column public.areas.place_cross is
  'The other street at a corner; null when the name is "Near ...".';
comment on column public.areas.place_number is
  '2, 3 ... when other live fires already had the same name; null otherwise.';

-- Every Area so far keeps its number as its code. Its name comes from the
-- streets once they are loaded (scripts/name_areas.py); until then it is
-- still called by its number.
update public.areas set area_code = designation where area_code is null;
