-- A private bucket for affiliate applications' SEC certificates (26 November
-- 2026, backend v1.12.53; answered "Real private upload").
--
-- Only the server reads and writes it (service role); the central hub opens a
-- certificate through a short-lived signed link. No object policy is created:
-- nobody else can read or write it. Re-runnable.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'affiliate-documents',
  'affiliate-documents',
  false,
  10485760,
  array['application/pdf', 'image/jpeg', 'image/png']
)
on conflict (id) do nothing;
