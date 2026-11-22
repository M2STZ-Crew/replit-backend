-- A fire declared under control (v1.12.49, 22 November 2026).
--
-- 22 Nov 2026: "fire alarm status can be seen in any details info", answered
-- "Level + situation": the alarm level, and Under control once a Fire
-- Volunteer or BFP coordinator (or an Admin who presses fire codes) declares
-- it with FC-2. It can be withdrawn. fire_code_events is an immutable log, so
-- what is in effect now is kept on the incident.
--
-- Nothing has to clear it on a raise: it is in effect only while it is newer
-- than alarm_level_set_at and the fire is live (app/services/alarm_status.py).
--
-- Additive and re-runnable: two nullable columns; no data changes. The
-- backend works without them (nobody is shown Under control, and withdrawing
-- answers migration_pending), so this can be applied before or after the
-- deploy.
--
-- To undo:
--   alter table public.areas
--     drop column if exists under_control_at,
--     drop column if exists under_control_by;

alter table public.areas
  add column if not exists under_control_at timestamptz,
  add column if not exists under_control_by uuid
    references public.users (id) on delete set null;

comment on column public.areas.under_control_at is
  'When a fire coordinator or Admin declared it under control (FC-2); in effect while newer than alarm_level_set_at.';
comment on column public.areas.under_control_by is
  'Who declared it under control.';
