-- Risk zones get a radius the Admin sets (Admin console, 24 Oct 2026).
--
-- A risk zone was a point (and an optional polygon nobody drew); the console
-- now draws each as its icon inside a circle, and the Admin sets how wide.
-- Existing zones start at 150 m.
--
-- Apply BEFORE deploying the backend that reads radius_m: until then the
-- risk-zone endpoints would fail.

alter table public.risk_zones
  add column if not exists radius_m double precision not null default 150
    constraint risk_zones_radius_range check (radius_m between 10 and 5000);

comment on column public.risk_zones.radius_m is
  'The zone''s circle around its centroid, in metres (10 to 5000; set by the Admin).';
