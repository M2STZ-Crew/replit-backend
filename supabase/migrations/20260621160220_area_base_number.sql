-- ============================================================================
-- Migration 0012 — areas.base_number for clustering designations (Phase 7)
-- "Area 1" (version 1) vs "Area 1.2"/"Area 1.3" (versions of the same location,
-- Section 3.4). base_number groups versions; a sequence avoids races for new areas.
-- ============================================================================
set search_path = public, extensions;

create sequence if not exists public.areas_base_number_seq;

alter table public.areas add column base_number integer;

create index areas_base_number_idx on public.areas (base_number);