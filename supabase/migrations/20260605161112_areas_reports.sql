-- ============================================================================
-- Migration 0004 — Areas, reports, junction, overlaps, neighborhood pushes
-- Tables: areas, reports, area_reports, area_overlaps, neighborhood_notifications
-- Plus:   late-bound FK on notification_log.area_id -> areas.id
-- Master context: Section 3.1 (image GPS cross-reference), Section 3.4 (area
--                 clustering + confidence + overlap), Section 3.5 (300 m push),
--                 Section 7 (#9-#13), Section 9 (7 lifecycle timestamps).
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- Enums introduced by this migration
-- ---------------------------------------------------------------------------

-- Dispatcher's decision when two area centroids are within 600 m (Section 3.4).
-- If unresolved within 120 s the application defaults to keep_separate.
create type public.overlap_decision as enum ('merge', 'keep_separate');
comment on type public.overlap_decision is
  'Dispatcher decision for overlapping area centroids within 600 m.';

-- Neighborhood-validation response (Section 3.5).
create type public.neighborhood_response as enum ('report', 'ignore');
comment on type public.neighborhood_response is
  'Per-user response to the 300 m crowdsourced neighborhood push.';

-- ---------------------------------------------------------------------------
-- areas (Section 7 #9) — one row per cluster
-- ---------------------------------------------------------------------------
create table public.areas (
  id                  uuid primary key default gen_random_uuid(),
  -- Human-readable designation, e.g. "Area 1", "Area 1.2"
  designation         text not null,
  -- Versioning chain for the same location within a 1 h window (Section 3.4).
  parent_area_id      uuid references public.areas (id) on delete set null,
  version             integer not null default 1 check (version >= 1),

  -- Cluster centroid (arithmetic mean of reporter coordinates).
  centroid_lat        double precision not null check (centroid_lat between -90 and 90),
  centroid_lng        double precision not null check (centroid_lng between -180 and 180),
  centroid            geography(Point, 4326) generated always as (
                        ST_SetSRID(ST_MakePoint(centroid_lng, centroid_lat), 4326)::geography
                      ) stored,

  -- Confidence components (Section 3.4):
  --   confidence_score = 0.4*N + 0.3*S + 0.3*V
  report_count        integer not null default 0 check (report_count >= 0),
  n_score             double precision not null default 0 check (n_score between 0 and 1),
  s_score             double precision not null default 0 check (s_score between 0 and 1),
  v_score             double precision not null default 0 check (v_score between 0 and 1),
  confidence_score    double precision not null default 0
                      check (confidence_score between 0 and 1),
  confidence_band     public.confidence_band generated always as (
                        case
                          when confidence_score >= 0.7 then 'high'::public.confidence_band
                          when confidence_score >= 0.4 then 'medium'::public.confidence_band
                          else 'low'::public.confidence_band
                        end
                      ) stored,

  -- Lifecycle (Section 9). Sequencing constraints are added in migration 0008.
  status              public.area_status not null default 'pending',
  reported_at         timestamptz not null default now(),
  verified_at         timestamptz,
  dispatched_at       timestamptz,
  en_route_at         timestamptz,
  arrived_at          timestamptz,
  resolved_at         timestamptz,
  rejected_at         timestamptz,

  -- Actor accountability for terminal/major transitions.
  verified_by         uuid references public.users (id) on delete set null,
  resolved_by         uuid references public.users (id) on delete set null,
  rejected_by         uuid references public.users (id) on delete set null,
  rejection_reason    text,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
comment on table public.areas is
  'Clustered fire incident areas with centroid, confidence, and the 7 lifecycle timestamps.';
comment on column public.areas.parent_area_id is
  'Original area in the 1 h versioning chain (Section 3.4); null for the first area.';
comment on column public.areas.confidence_score is
  '0.4*N + 0.3*S + 0.3*V (Section 3.4). N=min(reports/10,1), S=spatial tightness, V=mean reporter verification%.';

create index areas_centroid_idx on public.areas using gist (centroid);
create index areas_status_idx on public.areas (status);
create index areas_confidence_band_idx on public.areas (confidence_band);
create index areas_reported_at_idx on public.areas (reported_at);
create index areas_parent_idx on public.areas (parent_area_id);
-- Active-incidents partial index for the 60 s neighborhood scheduler (Phase 8).
create index areas_active_idx on public.areas (reported_at)
  where status not in ('resolved', 'rejected');

create trigger set_areas_updated_at
  before update on public.areas
  for each row execute function public.set_updated_at();

alter table public.areas enable row level security;

-- ---------------------------------------------------------------------------
-- reports (Section 7 #12) — individual citizen contributions
-- ---------------------------------------------------------------------------
create table public.reports (
  id                     uuid primary key default gen_random_uuid(),
  reporter_id            uuid references public.users (id) on delete set null,

  -- Device GPS, captured at submission (Section 2)
  device_lat             double precision not null check (device_lat between -90 and 90),
  device_lng             double precision not null check (device_lng between -180 and 180),
  device_gps_accuracy_m  double precision,
  device_location        geography(Point, 4326) generated always as (
                           ST_SetSRID(ST_MakePoint(device_lng, device_lat), 4326)::geography
                         ) stored,

  -- EXIF GPS extracted from the uploaded photo (Section 3.1); may be null
  exif_lat               double precision check (exif_lat is null or exif_lat between -90 and 90),
  exif_lng               double precision check (exif_lng is null or exif_lng between -180 and 180),
  exif_location          geography(Point, 4326) generated always as (
                           case
                             when exif_lat is not null and exif_lng is not null
                             then ST_SetSRID(ST_MakePoint(exif_lng, exif_lat), 4326)::geography
                             else null
                           end
                         ) stored,
  has_exif               boolean not null default false,

  -- Cross-reference outcome (Section 3.1, 100 m threshold)
  gps_discrepancy_m      double precision,
  gps_discrepancy_flag   boolean not null default false,

  -- Compass bearing is metadata only — NEVER used for geolocation (Section 2)
  compass_bearing        double precision
                         check (compass_bearing is null
                                or (compass_bearing >= 0 and compass_bearing < 360)),

  -- Media (Supabase Storage public/signed URLs)
  photo_url              text not null,
  photo_size_bytes       integer check (photo_size_bytes is null or photo_size_bytes > 0),
  video_url              text,
  video_size_bytes       integer check (video_size_bytes is null or video_size_bytes > 0),

  -- Multi-agency selection (Fire, Police, Medical, Barangay)
  selected_agencies      public.agency_type[] not null default '{}'::public.agency_type[],

  -- Reporter credibility snapshot at submission (Section 7)
  user_verified_percent  integer not null default 0
                         check (user_verified_percent between 0 and 100),

  notes                  text,

  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
comment on table public.reports is
  'Individual citizen incident contributions with v8 device-vs-EXIF GPS cross-reference.';
comment on column public.reports.compass_bearing is
  'Captured compass heading in degrees [0,360). Metadata only — not used for geolocation.';
comment on column public.reports.selected_agencies is
  'Which agencies the reporter wants notified: any of fire_volunteer, bfp, police, medical, barangay.';

create index reports_reporter_idx on public.reports (reporter_id);
create index reports_device_location_idx on public.reports using gist (device_location);
create index reports_created_idx on public.reports (created_at);
create index reports_discrepancy_idx on public.reports (created_at)
  where gps_discrepancy_flag;
create index reports_no_exif_idx on public.reports (created_at)
  where has_exif = false;

create trigger set_reports_updated_at
  before update on public.reports
  for each row execute function public.set_updated_at();

alter table public.reports enable row level security;

-- ---------------------------------------------------------------------------
-- area_reports (Section 7 #10) — junction: a report can belong to >1 area
-- ---------------------------------------------------------------------------
create table public.area_reports (
  id        uuid primary key default gen_random_uuid(),
  area_id   uuid not null references public.areas (id) on delete cascade,
  report_id uuid not null references public.reports (id) on delete cascade,
  added_at  timestamptz not null default now(),
  constraint area_reports_uniq unique (area_id, report_id)
);
comment on table public.area_reports is
  'Many-to-many junction; allows a single report to belong to multiple overlapping areas.';

create index area_reports_area_idx on public.area_reports (area_id);
create index area_reports_report_idx on public.area_reports (report_id);

alter table public.area_reports enable row level security;

-- ---------------------------------------------------------------------------
-- area_overlaps (Section 7 #11) — merge / keep-separate decisions
-- ---------------------------------------------------------------------------
create table public.area_overlaps (
  id           uuid primary key default gen_random_uuid(),
  area_a_id    uuid not null references public.areas (id) on delete cascade,
  area_b_id    uuid not null references public.areas (id) on delete cascade,
  distance_m   double precision not null check (distance_m >= 0),
  decision     public.overlap_decision,
  decided_by   uuid references public.users (id) on delete set null,
  decided_at   timestamptz,
  -- 120 s timeout (Section 3.4); the application defaults to keep_separate on expiry.
  expires_at   timestamptz not null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint area_overlaps_different check (area_a_id <> area_b_id),
  -- Canonical ordering prevents both (A,B) and (B,A) being logged.
  constraint area_overlaps_ordered check (area_a_id < area_b_id),
  constraint area_overlaps_pair_uniq unique (area_a_id, area_b_id)
);
comment on table public.area_overlaps is
  'Centroid-proximity (<600 m) overlap reviews with the 120 s default-to-separate timeout.';

create index area_overlaps_a_idx on public.area_overlaps (area_a_id);
create index area_overlaps_b_idx on public.area_overlaps (area_b_id);
create index area_overlaps_pending_idx on public.area_overlaps (expires_at)
  where decision is null;

create trigger set_area_overlaps_updated_at
  before update on public.area_overlaps
  for each row execute function public.set_updated_at();

alter table public.area_overlaps enable row level security;

-- ---------------------------------------------------------------------------
-- neighborhood_notifications (Section 7 #13) — 300 m alerts with 10-cap
-- ---------------------------------------------------------------------------
create table public.neighborhood_notifications (
  id           uuid primary key default gen_random_uuid(),
  area_id      uuid not null references public.areas (id) on delete cascade,
  user_id      uuid not null references public.users (id) on delete cascade,
  alerts_sent  integer not null default 0
               check (alerts_sent >= 0 and alerts_sent <= 10),  -- 10-cap (Section 3.5)
  last_sent_at timestamptz,
  response     public.neighborhood_response,
  responded_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint neighborhood_notifications_uniq unique (area_id, user_id)
);
comment on table public.neighborhood_notifications is
  '300 m crowdsourced validation tracking per (area, user) with the 10-alert cap and Report/Ignore response (Section 3.5).';

create index neighborhood_notifications_area_idx on public.neighborhood_notifications (area_id);
create index neighborhood_notifications_user_idx on public.neighborhood_notifications (user_id);
-- "Active" recipients still eligible for the next 60 s tick:
create index neighborhood_notifications_pending_idx
  on public.neighborhood_notifications (area_id, last_sent_at)
  where response is null and alerts_sent < 10;

create trigger set_neighborhood_notifications_updated_at
  before update on public.neighborhood_notifications
  for each row execute function public.set_updated_at();

alter table public.neighborhood_notifications enable row level security;

-- ---------------------------------------------------------------------------
-- Late-bound FK: notification_log.area_id (column created in 0003)
-- ---------------------------------------------------------------------------
alter table public.notification_log
  add constraint notification_log_area_id_fkey
  foreign key (area_id) references public.areas (id) on delete set null;