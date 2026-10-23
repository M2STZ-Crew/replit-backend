-- Alarm requests can be cancelled by whoever asked (Admin console, 24 Oct 2026).
--
-- A request BFP never answered stayed in its Inbox for good. POST
-- /alarm-requests/{id}/cancel now withdraws it: status 'cancelled', with who
-- did it in reviewed_by and when in reviewed_at. request_status is shared with
-- affiliate and map-layer requests; nothing there sets the new value.
--
-- Only adds an enum value, so it is safe to run before or after the backend
-- that uses it (until it runs, Cancel says to delete the request instead).

alter type public.request_status add value if not exists 'cancelled';

comment on type public.request_status is
  'Generic request status used by affiliate, alarm and map-layer requests; '
  'cancelled = withdrawn by whoever asked (alarm requests).';
