-- ============================================================================
-- Migration 0018 — area_status: add the 'merged' terminal value
-- Master context: Section 3.4 (Merge vs Keep Separate), Section 4.1 (areas.status
--                 includes 'merged'; areas.merged_into_area_id).
--
-- Until now a dispatcher [Merge] marked the absorbed area 'rejected' with
-- rejection_reason = 'merged', so every merge was counted as a false report in
-- any status-based analytics. 'merged' becomes its own terminal status.
--
-- SPLIT DEPLOY: PostgreSQL cannot use a new enum value in the same transaction
-- that adds it, and the Supabase CLI wraps each migration file in one. This file
-- therefore ONLY adds the value; the columns, constraints, index, and trigger
-- that reference it live in the next migration. Do not merge the two files.
-- ============================================================================

alter type public.area_status add value if not exists 'merged';
