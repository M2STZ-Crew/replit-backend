-- "I am safe" on the 150 m neighbourhood alert (31 Oct 2026, Issue 09; PRD v14
-- §4.2, §4.11).
--
-- A resident the alert reached can say they are safe: POST /notifications/respond
-- with response 'safe'. Like any answer it stops further alerts for that Area.
-- It is only ever set by that deliberate tap; being alerted says nothing about
-- whether someone is safe.
--
-- PRD §17 also lists need_help and not_in_area. They are not added here: "I need
-- help" promises that the responding Coordinator sees the resident's location,
-- and nothing delivers that yet.
--
-- Only adds an enum value, so it is safe to run before or after the backend
-- that uses it. Until it runs, answering "safe" fails and the app says the
-- answer was not recorded; Report and Ignore keep working.

alter type public.neighborhood_response add value if not exists 'safe';

comment on type public.neighborhood_response is
  'Answer to a 150 m neighbourhood alert: report (I see it too), ignore (stop asking), safe (I am safe).';
