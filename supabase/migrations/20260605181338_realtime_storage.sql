-- ============================================================================
-- Migration 0010 — Realtime publication & Storage buckets/policies
-- Master context: Section 5 (Supabase Storage + Realtime), Section 8 (real-time
--                 layer), Section 2 (photo/video/national-id storage).
-- ============================================================================

set search_path = public, extensions;

-- ---------------------------------------------------------------------------
-- Realtime: add operational tables to the default supabase_realtime publication
-- (Realtime honors RLS for the authenticated role, so subscribers only receive
-- rows their policies permit).
-- ---------------------------------------------------------------------------
alter publication supabase_realtime add table public.areas;
alter publication supabase_realtime add table public.reports;
alter publication supabase_realtime add table public.responder_locations;
alter publication supabase_realtime add table public.dispatch_logs;
alter publication supabase_realtime add table public.alarm_requests;
alter publication supabase_realtime add table public.neighborhood_notifications;
alter publication supabase_realtime add table public.fire_code_events;
alter publication supabase_realtime add table public.ai_summaries;

-- Full row image on change for updated lifecycle tables, so UPDATE/DELETE events
-- carry complete payloads and RLS can evaluate on them. High-volume insert-only
-- streams (responder_locations, fire_code_events, ai_summaries) keep the default.
alter table public.areas replica identity full;
alter table public.reports replica identity full;
alter table public.dispatch_logs replica identity full;
alter table public.alarm_requests replica identity full;
alter table public.neighborhood_notifications replica identity full;

-- ---------------------------------------------------------------------------
-- Storage buckets (all PRIVATE; the backend issues signed URLs).
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('incident-photos', 'incident-photos', false, 5242880,  array['image/jpeg','image/png']),  -- 5 MB
  ('incident-videos', 'incident-videos', false, 1572864,  array['video/mp4']),               -- 1.5 MB
  ('national-ids',    'national-ids',    false, 10485760, array['image/jpeg','image/png'])   -- 10 MB
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Storage object policies (RLS on storage.objects).
-- Convention: objects live under a top-level folder = owner's user id, e.g.
-- 'incident-photos/<user_id>/<filename>'. Uploads/writes go through the backend
-- (service_role bypasses these). These SELECT policies scope direct reads.
-- ---------------------------------------------------------------------------
create policy "incident_photos_read" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'incident-photos'
    and ((select public.is_staff())
         or (storage.foldername(name))[1] = (select auth.uid())::text)
  );

create policy "incident_videos_read" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'incident-videos'
    and ((select public.is_staff())
         or (storage.foldername(name))[1] = (select auth.uid())::text)
  );

create policy "national_ids_read_admin" on storage.objects
  for select to authenticated
  using (bucket_id = 'national-ids' and (select public.is_admin()));