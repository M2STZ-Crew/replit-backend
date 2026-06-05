-- ============================================================================
-- Migration 0007 — Equipment & map layers
-- Tables: equipment, hydrants, evacuation_sites, risk_zones, bodies_of_water,
--         underground_cisterns, map_layer_update_requests
-- Master context: Section 2 (GIS layers), Section 7 (#21-#26),
--                 Section 6 (Barangay/Medical/Police update requests),
--                 Phase 12 (map CRUD, hydrant override, CSV import).
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type public.equipment_status as enum (
  'available', 'in_use', 'maintenance', 'out_of_service'
);
comment on type public.equipment_status is 'Operational state of an equipment item.';

create type public.hydrant_status as enum (
  'operational', 'non_operational', 'under_maintenance', 'unknown'
);
comment on type public.hydrant_status is 'Hydrant/cistern working status (BFP-synced or ground-truth).';

create type public.risk_level as enum ('low', 'medium', 'high', 'critical');
comment on type public.risk_level is 'BFP per-barangay fire-risk classification.';

create type public.map_layer_type as enum (
  'hydrant', 'evacuation_site', 'risk_zone',
  'bodies_of_water', 'underground_cistern', 'equipment'
);
comment on type public.map_layer_type is 'Target layer for a map-layer update request.';

create type public.map_layer_operation as enum ('create', 'update', 'delete');
comment on type public.map_layer_operation is 'Requested change type for a map-layer update.';

-- ---------------------------------------------------------------------------
-- equipment (Section 7 #21) — per-organization items
-- ---------------------------------------------------------------------------
create table public.equipment (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references public.organizations (id) on delete cascade,
  name             text not null,
  category         text,
  quantity         integer not null default 1 check (quantity >= 0),
  status           public.equipment_status not null default 'available',
  serial_number    text,
  description      text,
  last_serviced_at timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
comment on table public.equipment is 'Equipment inventory scoped to an organization (Section 7 #21).';

create index equipment_org_idx on public.equipment (organization_id);
create index equipment_status_idx on public.equipment (status);

create trigger set_equipment_updated_at
  before update on public.equipment
  for each row execute function public.set_updated_at();

alter table public.equipment enable row level security;

-- ---------------------------------------------------------------------------
-- hydrants (Section 7 #22) — BFP-synced status + Fire-Vol ground-truth override
-- ---------------------------------------------------------------------------
create table public.hydrants (
  id                  uuid primary key default gen_random_uuid(),
  code                text,
  latitude            double precision not null check (latitude between -90 and 90),
  longitude           double precision not null check (longitude between -180 and 180),
  location            geography(Point, 4326) generated always as (
                        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                      ) stored,
  address             text,
  -- BFP-synced status (monthly CSV import, Admin only).
  bfp_status          public.hydrant_status not null default 'unknown',
  bfp_synced_at       timestamptz,
  -- Fire-Volunteer ground-truth override (Section 12).
  ground_truth_status public.hydrant_status,
  ground_truth_by     uuid references public.users (id) on delete set null,
  ground_truth_at     timestamptz,
  ground_truth_notes  text,
  -- Effective status: the override wins when present.
  effective_status    public.hydrant_status generated always as (
                        coalesce(ground_truth_status, bfp_status)
                      ) stored,
  source              text not null default 'manual',
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.hydrants is
  'Fire hydrants with BFP-synced status and Fire-Volunteer ground-truth overrides; effective_status = override else bfp_status (Section 7 #22, Phase 12).';

create index hydrants_location_idx on public.hydrants using gist (location);
create index hydrants_effective_status_idx on public.hydrants (effective_status);
create index hydrants_code_idx on public.hydrants (code) where code is not null;

create trigger set_hydrants_updated_at
  before update on public.hydrants
  for each row execute function public.set_updated_at();

alter table public.hydrants enable row level security;

-- ---------------------------------------------------------------------------
-- evacuation_sites (Section 7 #23)
-- ---------------------------------------------------------------------------
create table public.evacuation_sites (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  latitude     double precision not null check (latitude between -90 and 90),
  longitude    double precision not null check (longitude between -180 and 180),
  location     geography(Point, 4326) generated always as (
                 ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
               ) stored,
  capacity     integer check (capacity is null or capacity >= 0),
  address      text,
  contact_info text,
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
comment on table public.evacuation_sites is 'Designated evacuation sites map layer (Section 7 #23).';

create index evacuation_sites_location_idx on public.evacuation_sites using gist (location);

create trigger set_evacuation_sites_updated_at
  before update on public.evacuation_sites
  for each row execute function public.set_updated_at();

alter table public.evacuation_sites enable row level security;

-- ---------------------------------------------------------------------------
-- risk_zones (Section 7 #24) — pre-loaded BFP per-barangay data
-- ---------------------------------------------------------------------------
create table public.risk_zones (
  id           uuid primary key default gen_random_uuid(),
  barangay     text not null,
  name         text,
  risk_level   public.risk_level not null default 'medium',
  description  text,
  -- Optional boundary polygon (GeoJSON-derived); representative point required.
  area_geom    geography(Polygon, 4326),
  centroid_lat double precision not null check (centroid_lat between -90 and 90),
  centroid_lng double precision not null check (centroid_lng between -180 and 180),
  centroid     geography(Point, 4326) generated always as (
                 ST_SetSRID(ST_MakePoint(centroid_lng, centroid_lat), 4326)::geography
               ) stored,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
comment on table public.risk_zones is 'BFP per-barangay fire-risk zones (Section 7 #24).';

create index risk_zones_centroid_idx on public.risk_zones using gist (centroid);
create index risk_zones_area_idx on public.risk_zones using gist (area_geom);
create index risk_zones_barangay_idx on public.risk_zones (barangay);
create index risk_zones_level_idx on public.risk_zones (risk_level);

create trigger set_risk_zones_updated_at
  before update on public.risk_zones
  for each row execute function public.set_updated_at();

alter table public.risk_zones enable row level security;

-- ---------------------------------------------------------------------------
-- bodies_of_water (Section 7 #25)
-- ---------------------------------------------------------------------------
create table public.bodies_of_water (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  water_type    text,
  latitude      double precision not null check (latitude between -90 and 90),
  longitude     double precision not null check (longitude between -180 and 180),
  location      geography(Point, 4326) generated always as (
                  ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                ) stored,
  area_geom     geography(Polygon, 4326),
  is_accessible boolean not null default true,
  description   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.bodies_of_water is
  'Bodies of water usable as firefighting water sources, map layer (Section 7 #25).';

create index bodies_of_water_location_idx on public.bodies_of_water using gist (location);
create index bodies_of_water_area_idx on public.bodies_of_water using gist (area_geom);

create trigger set_bodies_of_water_updated_at
  before update on public.bodies_of_water
  for each row execute function public.set_updated_at();

alter table public.bodies_of_water enable row level security;

-- ---------------------------------------------------------------------------
-- underground_cisterns (Section 7 #26)
-- ---------------------------------------------------------------------------
create table public.underground_cisterns (
  id              uuid primary key default gen_random_uuid(),
  name            text,
  code            text,
  latitude        double precision not null check (latitude between -90 and 90),
  longitude       double precision not null check (longitude between -180 and 180),
  location        geography(Point, 4326) generated always as (
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                  ) stored,
  capacity_liters integer check (capacity_liters is null or capacity_liters >= 0),
  status          public.hydrant_status not null default 'unknown',
  address         text,
  description     text,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
comment on table public.underground_cisterns is
  'Underground water cisterns map layer (Section 7 #26). Reuses hydrant_status for working state.';

create index underground_cisterns_location_idx on public.underground_cisterns using gist (location);
create index underground_cisterns_status_idx on public.underground_cisterns (status);

create trigger set_underground_cisterns_updated_at
  before update on public.underground_cisterns
  for each row execute function public.set_updated_at();

alter table public.underground_cisterns enable row level security;

-- ---------------------------------------------------------------------------
-- map_layer_update_requests (Section 7 #26, Section 6) — Barangay/Medic/Police
-- ---------------------------------------------------------------------------
create table public.map_layer_update_requests (
  id              uuid primary key default gen_random_uuid(),
  requested_by    uuid not null references public.users (id) on delete cascade,
  organization_id uuid references public.organizations (id) on delete set null,
  layer_type      public.map_layer_type not null,
  operation       public.map_layer_operation not null,
  -- Existing record being changed (null for 'create').
  target_id       uuid,
  proposed_data   jsonb not null default '{}'::jsonb,
  reason          text,
  status          public.request_status not null default 'pending',
  reviewed_by     uuid references public.users (id) on delete set null,
  reviewed_at     timestamptz,
  review_notes    text,
  applied_at      timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint map_layer_requests_target_for_mutation check (
    case
      when operation in ('update', 'delete') then target_id is not null
      else true
    end
  )
);
comment on table public.map_layer_update_requests is
  'Barangay/Medical/Police sub-admin requests to add/update/remove map-layer or equipment records (Section 6, Phase 12).';

create index map_layer_requests_requested_by_idx on public.map_layer_update_requests (requested_by);
create index map_layer_requests_status_idx on public.map_layer_update_requests (status);
create index map_layer_requests_layer_idx on public.map_layer_update_requests (layer_type);
create index map_layer_requests_pending_idx on public.map_layer_update_requests (created_at)
  where status = 'pending';

create trigger set_map_layer_requests_updated_at
  before update on public.map_layer_update_requests
  for each row execute function public.set_updated_at();

alter table public.map_layer_update_requests enable row level security;