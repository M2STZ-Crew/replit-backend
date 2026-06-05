-- ============================================================================
-- Migration 0011 — Seed data
-- Master context: Section 5 (seed data), Phase 13 (fire_codes seed).
-- All inserts are idempotent. Sample geo/code values are PLACEHOLDERS to be
-- replaced with the partner organizations' / BFP's authoritative data.
-- No users are seeded — the first admin is created via Supabase Auth in Phase 3.
-- ============================================================================

set search_path = public, extensions;

-- Fire codes (SAMPLE — replace with the partner brigades' official code list).
insert into public.fire_codes (code_number, name, description, target_role, display_order)
values
  ('FC-1', 'On Scene / Arrived',     'Responding unit has arrived at the incident.',        'response_team', 1),
  ('FC-2', 'Fire Under Control',     'Fire is contained and no longer spreading.',          'response_team', 2),
  ('FC-3', 'Fire Out',               'Fire has been extinguished.',                          'response_team', 3),
  ('FC-4', 'Overhauling',            'Checking for and extinguishing hidden/residual fire.', 'response_team', 4),
  ('FC-5', 'Returning to Station',   'Unit is returning to base.',                           'response_team', 5),
  ('FC-6', 'Water Supply Needed',    'Additional water source/tanker required.',             'response_team', 6),
  ('FC-7', 'Additional Units Needed','Request for more responding units.',                   'sub_admin',     7),
  ('FC-8', 'Possible Casualty',      'Possible injured person(s) at the scene.',             'response_team', 8)
on conflict (code_number) do nothing;

-- Sample partner organization (Pasay City fire volunteer brigade).
insert into public.organizations (name, agency_type, description, address, latitude, longitude)
select 'Hercules Fire Brigade', 'fire_volunteer',
       'Volunteer fire brigade partner organization (sample seed).',
       'Pasay City, Metro Manila', 14.53780, 120.99470
where not exists (
  select 1 from public.organizations where name = 'Hercules Fire Brigade'
);

-- Sample barangay risk zones (SAMPLE centroids — replace with BFP per-barangay data).
insert into public.risk_zones (barangay, name, risk_level, description, centroid_lat, centroid_lng)
select v.barangay, v.name, v.risk_level, v.description, v.centroid_lat, v.centroid_lng
from (values
  ('Barangay 76',  'Zone 10', 'high'::public.risk_level,   'Sample high-risk zone (partner area).', 14.54100, 120.99800),
  ('Barangay 201', 'Zone 20', 'medium'::public.risk_level, 'Sample medium-risk zone.',              14.52500, 120.99000),
  ('Barangay 178', 'Zone 19', 'high'::public.risk_level,   'Sample high-risk zone.',                14.53000, 121.00200)
) as v(barangay, name, risk_level, description, centroid_lat, centroid_lng)
where not exists (
  select 1 from public.risk_zones r where r.barangay = v.barangay
);