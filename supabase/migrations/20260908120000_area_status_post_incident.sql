-- ============================================================================
-- Migration 0020 — area_status: add 'post_incident_report' and 'closed'
-- Master context v10: Section 2.5 (the Post-Incident Report step sits between
--                     'resolved' and the terminal 'closed'), Section 4.3.
--
-- SPLIT DEPLOY, as with 0018: PostgreSQL cannot use a new enum value in the
-- transaction that adds it, and the Supabase CLI wraps each migration file in
-- one. This file therefore ONLY adds the values; the columns, constraints,
-- triggers and tables that reference them live in the next migration. Do not
-- merge the two files.
--
-- Both values anchor on 'resolved' (already committed) rather than on each
-- other, so neither statement depends on a value added in this transaction.
-- Adding 'closed' first and then 'post_incident_report' yields the lifecycle
-- order: ... resolved, post_incident_report, closed, rejected, merged.
-- ============================================================================

alter type public.area_status add value if not exists 'closed' after 'resolved';
alter type public.area_status add value if not exists 'post_incident_report' after 'resolved';
