# Admin console — pass 6 frontend handoff

For Justine (backend). This records what the Admin console's pass 6 redesign
(Figma REPLIT (MAIN), page 10, frames A00–A85) does today, what is prepared
for features the server does not support yet, and what each prepared screen
needs from the server before it can be wired.

Baseline: API v1.12.8 (`origin/main` d1a343c). No backend code, schema,
migration, API contract, authorization rule or deployment setting was changed.

**Update, 23 Oct 2026 — one console, an Admin per organisation (ARBAC).** The
server now reports each Admin's standing on `GET /auth/me` as `console`
(variant, scope, organisation, `act_agencies`, permissions;
`app/services/access.py`) and enforces it. The console reads it in
`src/lib/access.js`. Rows below marked *(ARBAC)* changed with it. Preview each
organisation's console at `/docs/console-preview.html?as=police` (or `bfp`,
`fire_volunteer`, `medical`, `barangay`, `central`, `system`). Migration
`20261023180000_admin_console_access.sql` adds `organizations.is_central_hub`
and lets the BFP Admin set the alarm level; the API runs without it.

## Statuses used below

- **INTEGRATED** — in the live console, on real endpoints, with loading,
  empty, failed and success states.
- **UI READY** — built and shown in `/docs/console-ready.html` with fictional
  data; not reachable from the console's navigation. Needs a server contract.
- **NEEDS DECISION** — a product decision is open before it can be built or
  wired.
- **BLOCKED** — excluded on purpose (the brief, or no server support and no
  sensible prepared screen).

## Coverage matrix

| Frame(s) | Screen | Status | Notes |
|---|---|---|---|
| A00 | Screen map | — | Reference only. Sidebar destinations match it. |
| A01 | Sign in | INTEGRATED | Adds "Forgot password?" on `POST /auth/recover` (same generic answer whether or not the address exists). |
| A02, A02b | Wrong password, account not set up | INTEGRATED | Server's error message shown; non-Admin accounts are refused after sign-in (`auth.jsx`). |
| A03, A04 | Affiliate request form, sent | INTEGRATED | `POST /affiliates/register`. Form keeps the server's roster, equipment and SEC-certificate fields. |
| A05 | Affiliate requests | INTEGRATED | Waiting, Accepted, Declined, plus "On the network" (every organisation, opens its people and equipment). |
| A06, A06b | Accept, accepted | INTEGRATED | Copy says what the server does: creates the organisation and a **Coordinator** account, emails a password link. Shows `invite_email_sent` / `account_provisioned` / `detail` as returned. No 48-hour claim. |
| A06c | Decline | INTEGRATED | Reason required (kept from the old console). Says the server sends no email. |
| A07–A11 | Admin registration link | UI READY | `pages/AdminRegistration.jsx`. Needs: token validation, prefix check, account creation. |
| A12 | First sign-in, new organisation | BLOCKED | No first-sign-in state on the server. |
| A20, A21 | Dashboard | INTEGRATED *(ARBAC)* | Queues this Admin answers. An organisation's Admin gets "Routed to <org>" with the Your org chip, then "Other organisations' incidents", view only. |
| A21 | New-incident alarm cards | INTEGRATED | Opening stops the sound and does not acknowledge. |
| A22 | Incidents | INTEGRATED *(ARBAC)* | Search, status, agency and confidence filters; All active, Routed to you, Closed; Your org column. |
| A23, A24, A24b | Incident detail, acknowledge, acknowledged | INTEGRATED | `POST /incidents/{id}/accept`. Admin Reject removed (PRD v13 §4.5.2). |
| A25 | View only (not routed to you) | INTEGRATED *(ARBAC)* | An Area that did not ask for the Admin's agency. Reporters' names, photos and positions are withheld (server 403). |
| A26 | On scene | INTEGRATED | Units from `/dispatches`, alarm escalations for the Area. |
| A27, A27b | Possible duplicate, merge | INTEGRATED | `/areas/overlaps/pending`, `/merge`, `/keep-separate`; 120 s window; B is absorbed into A. |
| A28 | Declined on scene | BLOCKED | Server has no `declined` status. Drawn as "Declined" only if it ever arrives; `rejected` is never relabelled. |
| A30, A31 | Live map, selected incident | INTEGRATED | 300 m Area radius (the server's `_CLUSTER_RADIUS_M`, not v13's 100 m). Units not drawn: the server cannot scope them to the Admin's organisation. |
| A32, A33 | Water resources list and map | INTEGRATED | Hydrants, bodies of water, cisterns. No level percentages (not stored). |
| A34, A34b | Resource detail, delete | INTEGRATED | Admin `DELETE /map/{type}/{id}`. |
| A35 | Add or update a resource | INTEGRATED | In Map settings on the Live map, for the central hub (`map.manage`). |
| A40, A41 | Requests, request detail | INTEGRATED | Alarm escalations only (`GET /alarm-requests`), read only. Answer card says a BFP Coordinator decides on mobile. |
| A42 | Sent requests | BLOCKED | An Admin cannot raise a request, so Sent is always empty. |
| A43, A44 | New water or backup request | UI READY | `components/requests/NewRequestDialog.jsx`. Needs Admin-to-Admin requests. |
| A45, A46, A46b | Alarm escalation, BFP decides, set level | INTEGRATED *(ARBAC)* | Fire Volunteer Admin asks (Requests › New request, or on scene in the incident); BFP Admin sets the level or declines. Setting needs migration 20261023180000. Task Force levels are not offered (none on the server). |
| A47 | Organisation | INTEGRATED | The Admin's own organisation (`primary_org_id`): profile, people counts, equipment. |
| A48 | Accounts | INTEGRATED *(ARBAC)* | Own organisation's Coordinators (email, title, status, created by) and Responders, view only. Turn off / on. |
| A49, A49b | Create a Coordinator | INTEGRATED *(ARBAC)* | `POST /admin/coordinators`: own organisation, emailed a set-password link. |
| A50, A51 | ID reviews | INTEGRATED | Photos hidden until Show; approve; ask to try again (reason required). |
| A60, A61 | Reports, filed report | INTEGRATED | PIR list and detail, AI summary tab, PDF download. |
| A62, A63, A63b | CIAR six parts, generating, failed | UI READY | `components/reports/CiarView.jsx`. The server writes a narrative summary, shown on A61's AI summary tab. |
| A64 | Audit log | INTEGRATED | Search, Area and action filters. Actor column shows role and agency (no name stored). |
| A65, A66 | Correction entries | UI READY | `components/audit/CorrectionDialog.jsx`. |
| A70 | Settings | INTEGRATED | Per-category sound and mute, test, ring-again interval, desktop alerts. |
| A71 | AFK on | UI READY | `AvailabilityPanel` in `pages/Settings.jsx`. |
| A72 | Another Admin sees an AFK organisation | BLOCKED | No availability is stored or returned. |
| A80, A81, A82 | Empty, loading, couldn't load | INTEGRATED | On every list. On Dashboard and Incidents a failed refresh keeps the last list, dimmed, with "Last loaded". |
| A83, A84 | 1280 × 800 | INTEGRATED | Full sidebar; it scrolls when the central-hub list is taller than the window. |
| A85 | 1024 × 768 | INTEGRATED | 72 px rail; incidents as stacked cards below 1280 px. |

## Decisions taken in the frontend

- `verified` is labelled **Acknowledged** (PRD v13 §4.5 renames the label of
  the same act). Requests and filters still send `verified`.
- Central hub: the server says which organisation is the hub
  (`organizations.is_central_hub`); only its Admins and the system Admin get
  Verification and Affiliates. Before the migration no organisation is the
  hub.
- No "Backend pending" text appears on user-facing screens. Missing columns
  and controls are left out, and the reason is written in the component's
  header comment.
- Fixed bug: alarm levels were keyed `positive`; the server sends
  `positive_fire_alarm`. Labels now live in `lib/status.js` (`alarmLabel`).

## What each UI READY screen needs

Each component takes plain data and callbacks; nothing calls the API.
Signatures are in each file's header comment.

| Component | Callback | Server work it waits on |
|---|---|---|
| `NewRequestDialog` | `onSend({ kind, areaId, toOrganizationId, amount?, role?, count?, urgency })` | Admin-to-Admin requests (PRD v13 §4.7): create, list inbox and sent, reply (accept, decline, acknowledge). Roles and units come from the server. |
| `AvailabilityPanel` | `onChange(next)` | Store and return each organisation's AFK flag and since-time (PRD v13 §4.6.5). |
| `CiarView` | `onRetry()` | A structured, immutable CIAR per Area with its parts, plus generating and failed states. |
| `CorrectionDialog` | `onSubmit({ field, was, now, reason })` | Correction entries in the audit log, linked to the record they correct. |
| `AdminRegistration` | `checkPrefix(prefix)`, `onCreate({ prefix, email })` | One-time registration tokens (valid, expired, used), prefix availability, Admin account creation. The prefix rule and email domain are props: the server owns them. |

## Endpoints the console calls

All existed before this pass. New client helpers: `recover`,
`alarmRequests(status)`, `pendingOverlaps`, `overlapMerge`,
`overlapKeepSeparate`, `postIncidentReportList`, `incidentSummaries`.

## Server observations (not changed here)

- The password-reset page tells everyone to "open the RepLiT app". An Admin
  signs in on the web.
- `GET /organizations/{id}/personnel` returns no email, so Accounts cannot show
  one.
- The audit log stores no actor name.

## Mobile

The mobile pass 6 has not been done in this pass. The mobile feature branch
(`feat/pass6-frontend`) holds typed models and widget drafts only; it is not
merged and not part of this commit.

## Previews

See [PREVIEW.md](PREVIEW.md).
