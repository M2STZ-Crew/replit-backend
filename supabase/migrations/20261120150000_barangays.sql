-- Barangays: where a fire is, and an outline layer (v1.12.45, 20 Nov 2026).
--
-- 19 Nov 2026: "Concha Street corner Camba Street, Barangay 70 Zone 10, Tondo,
-- Manila ... we are covering metro manila for now", and "barangay map outline
-- refers to the exact geographic boundary lines (polygons) of each barangay,
-- displayed as a clean layer so you can color-code and highlight fire risk
-- zones". Answered: PSA/NAMRIA's outlines (UN OCHA COD-AB v03), zones and
-- Manila's districts from Wikipedia's lists, every map, switchable, with
-- Pasay's eight High fire-risk zones (research-based, never a BFP
-- designation). docs/data-sources.md cites each source.
--
-- public.barangays: Metro Manila's 1,712 barangays, loaded by
-- scripts/load_barangays.py from docs/barangays/. geom is in UTM zone 51N
-- (EPSG:32651) like public.streets, so "which barangay is this point in, or
-- within 100 m of" is metres on a plane with a GiST index; geom_map is the
-- outline simplified to 2 m in EPSG:4326, for the map layer.
--
-- public.fire_risk_barangays: the 86 barangays of Pasay's Zones 8, 11, 13,
-- 14, 15, 16, 19 and 20, High, from RepLiT's research-based assessment. The
-- checks keep it what it is: High only, never an official BFP designation.
--
-- areas.place_line is a fire's full place ("Near F. Victor Street, Barangay
-- 76 Zone 10, Pasay"), for detail screens and the report; areas.designation
-- becomes the short form every alert already reads ("Near F. Victor St.,
-- Brgy 76, Pasay"). areas.barangay_pcode is the barangay it was named in.
--
-- Additive: the backend before v1.12.45 reads none of it, and v1.12.45 names
-- fires as v1.12.42 did until this is applied and the barangays are loaded.

create table if not exists public.barangays (
  pcode       text primary key,
  psa_name    text not null,
  name        text not null,
  kind        text not null check (kind in ('numbered', 'named', 'special')),
  number      text,
  zone        integer,
  district    text,
  city        text not null,
  city_pcode  text not null,
  geom        extensions.geometry(MultiPolygon, 32651) not null,
  geom_map    extensions.geometry(MultiPolygon, 4326) not null
);

create index if not exists barangays_geom_gist on public.barangays using gist (geom);

-- Read by the server only.
alter table public.barangays enable row level security;

comment on table public.barangays is
  'Metro Manila''s barangays: PSA/NAMRIA outlines (UN OCHA COD-AB v03, CC BY-IGO 3.0), '
  'zones and Manila''s districts from Wikipedia (CC BY-SA 4.0). Names fires and draws '
  'the barangay layer (v1.12.45).';
comment on column public.barangays.pcode is 'PSA''s PSGC code, as COD-AB writes it: PH1307605076.';
comment on column public.barangays.name is
  'What a place says: "Barangay 76", "Bel-Air", "Tutuban Mall" (PSA''s name without a trailing note).';
comment on column public.barangays.kind is
  'numbered (Manila, Pasay, Caloocan: "Barangay 76 Zone 10"), named, or special '
  '(Manila North Cemetery, Tutuban Mall).';
comment on column public.barangays.district is 'Manila''s district (Tondo, Sampaloc ...); null elsewhere.';
comment on column public.barangays.city is
  'The city''s short name: Pasay, Manila, Quezon City. The ten EMBO barangays are Taguig.';
comment on column public.barangays.geom is 'The outline in EPSG:32651 (metres), for lookups.';
comment on column public.barangays.geom_map is 'The outline simplified to 2 m, in EPSG:4326, for the map.';

create table if not exists public.fire_risk_barangays (
  pcode                    text primary key references public.barangays (pcode) on delete cascade,
  zone_id                  integer not null,
  barangay_no              text not null,
  risk_level               text not null check (risk_level = 'High'),
  risk_source              text not null,
  assessment_start         date not null,
  assessment_end           date not null,
  official_bfp_designation boolean not null default false check (not official_bfp_designation)
);

alter table public.fire_risk_barangays enable row level security;

comment on table public.fire_risk_barangays is
  'Pasay''s High fire-risk zones (8, 11, 13, 14, 15, 16, 19, 20), from RepLiT''s '
  'research-based fire incident assessment: "High fire-risk zone (research-based)", '
  'never an official BFP designation (v1.12.45).';

alter table public.areas
  add column if not exists place_line     text,
  add column if not exists barangay_pcode text references public.barangays (pcode) on delete set null;

comment on column public.areas.place_line is
  'The full place for detail screens and the report: "Near F. Victor Street, Barangay 76 '
  'Zone 10, Pasay". designation holds the short form alerts use (v1.12.45).';
comment on column public.areas.barangay_pcode is 'The barangay the fire was named in.';
