# Changelog

Versions follow `MAJOR.MINOR.PATCH`. MINOR tracks the Master Context generation
(1.12.x implements `MASTER_CONTEXT_v12.md`); the backend, both web consoles and
the mobile app (`replit-android`) carry the same number.

---

## v1.12.4 — 5 October 2026 — Coordinators make their responders' accounts

(1.12.2 and 1.12.3 were app-only releases; the backend and consoles go from
1.12.1 straight to 1.12.4 so all four carry the same number again.)

### Changes

**Added**
- **Responder accounts, made by the team captain** (Master Context v12
  §2.6.3). Every sub-admin — a Fire Volunteer or BFP coordinator in the app,
  a police, medical or barangay captain in the Observer Console — creates the
  Response Team accounts of their own agency and team:
  - the address follows the account directory: first initial + full surname,
    `.res` + agency (`fir`, `bfp`, `pol`, `med`, `bar`), `@replit.com` —
    `jdelacruz.resfir@replit.com`; when the same role already has that name,
    the next number goes straight after the surname (`jdelacruz1.resfir`);
  - the password is generated and returned **once**, for the captain to hand
    over in person (@replit.com has no mailboxes);
  - **Reset password** (a new temporary one, once) and **Deactivate /
    Reactivate**.
- `GET /team/responders`, `GET /team/responders/email-preview`,
  `POST /team/responders`, `POST /team/responders/{id}/reset-password`,
  `/deactivate`, `/reactivate` (sub-admins only, own agency and team).
- Observer Console: a **Responders** section (sidebar and phone bar).

**Modified**
- A deactivated account is refused on **every** request and on the socket
  (401, "This account has been deactivated. Ask your coordinator to reactivate
  it."), not only at its next sign-in; signing in says the same instead of
  Supabase's "User is banned".

### Files Changed
- New: `app/api/routes/team.py`, `app/schemas/team.py`,
  `app/services/responder_accounts.py`,
  `supabase/migrations/20261005090000_responder_accounts.sql`,
  `observer-web/src/pages/RespondersPage.jsx`, `tests/test_team.py`.
- `app/api/deps.py` (`SubAdminUser`, the active check), `app/api/routes/ws.py`
  (the active check), `app/api/routes/auth.py` (the deactivated sign-in
  message), `app/api/routes/__init__.py`.
- `observer-web/src/App.jsx`, `observer-web/src/components/ObserverShell.jsx`,
  `observer-web/src/api/client.js`, `observer-web/src/index.css`.
- `MASTER_CONTEXT_v12.md` — §2.6.1 navigation, new §2.6.3, §5.1.
- `pyproject.toml`, `uv.lock`, `app/core/config.py`, `admin-web/package.json`,
  `observer-web/package.json` — version 1.12.4.

### Database Changes
- `public.users` + `is_active boolean not null default true`,
  `deactivated_at timestamptz`, `deactivated_by uuid`, `created_by uuid`
  (both → `users`, on delete set null); index `users_staff_roster_idx`
  (responders by agency and team).
- **Migration requirement: apply `20261005090000_responder_accounts.sql`
  before deploying this backend.** The API reads `users.is_active` on every
  request, so this backend without the column refuses everyone. Additive and
  idempotent; every existing account stays active.

### API Changes
| Endpoint | Change |
|---|---|
| `GET /team/responders` | **New.** The caller's responders (agency + team), active first; `responding` when on a live response. |
| `GET /team/responders/email-preview?first_name&last_name` | **New.** The address that name would get now. |
| `POST /team/responders` | **New.** `{first_name, last_name, mobile?}` → 201 `{responder, email, temporary_password}`. A race for the same address takes the next number. |
| `POST /team/responders/{id}/reset-password` | **New.** → `{responder, email, temporary_password}`; 409 while deactivated. |
| `POST /team/responders/{id}/deactivate` · `/reactivate` | **New.** Ban / unban in Supabase Auth, `users.is_active`; deactivate releases a live response and stops pushes. |
| Every authenticated route, the socket | A deactivated account → 401 / socket refused. |
| `POST /auth/login` | A deactivated account → 401 with the deactivated message. |

Another team's or agency's responder → 404; anyone but a sub-admin → 403.
Audit actions: `user.responder_created`, `user.responder_password_reset`,
`user.responder_deactivated`, `user.responder_reactivated`.

### Frontend Changes
- Observer Console: Responders (list, New responder with the live address,
  the one-time credentials with Copy, Reset password, Deactivate/Reactivate);
  a card per responder on a phone.
- Mobile (`replit-android` v1.12.4): menu → Responders for coordinators — see
  that repository's `CHANGELOG.md`.

### Testing
- The address: every agency's suffix; the directory's own examples; accents,
  spaces and case flattened; the first keeps the plain address, later ones
  numbered after the surname; numbers count only the same role and name and
  run on after a removal; unknown agencies refused.
- The password: strong, readable, unique.
- Create: own agency and team, mobile normalised, audit row; a race for the
  address takes the next number; only a sub-admin (responder, citizen and
  Admin → 403); the preview.
- Roster: own team and agency only; another team's responder 404 for every
  action.
- Reset: a new password, once. Deactivate: banned, response released, pushes
  stopped, account kept, audit row; reset refused until reactivated;
  reactivate lifts the ban. A deactivated account is refused on a request.
- Observer Console page driven in a browser against a local stand-in API
  (create with a live third-of-a-name address, reset, reactivate, phone
  layout); no console errors.
- Result: the whole backend suite passes; `ruff` clean; `mypy` clean apart
  from the pre-existing `app/services/ai_summary.py:72` (not touched here);
  both consoles build.

### Regression Check
Full backend suite passes. Every existing account is active by default, so
nothing changes for anyone until a captain deactivates someone.

---

## v1.12.1 — 30 September 2026 — Who verified a fire, and for which organization

### Changes

**Added**
- **The verifier's organization.** Wherever an incident shows who verified it,
  it now also shows the team they verified it for — as recorded at the moment
  they pressed Verify (the `is_first` row of `area_acceptances`), so a later
  change of brigade does not rewrite it. Incidents verified before v11 fall
  back to the verifier's current team.
- **The citizen is told which team verified their report**: Track It Live
  shows "Verified by Hercules Fire Brigade", and the "Report verified" push
  says "verified by Hercules Fire Brigade". The team only, never the person
  (decided 30 Sep 2026), the same rule Track It Live keeps for units. A
  verifier with no team is named by agency; an Admin as "RepLiT Admin".

**Modified**
- Observer Console: the Verified fact reads "time · name (organization)".

**Unchanged, confirmed**
- The fire truck on the citizen's map: the reporter's Track It Live already
  draws each responding unit — responders and responding coordinators alike —
  as a moving fire-truck marker from their first GPS fix, while the incident
  is On the way or On scene.

### Files Changed
- `app/services/verifier.py` — new: `fetch_verifier`, `Verifier.public_label`.
- `app/schemas/incident.py`, `app/api/routes/incidents.py` —
  `IncidentDetail.verified_by_organization`, `verified_by_agency`.
- `app/schemas/tracking.py`, `app/services/tracking.py` —
  `TrackingSnapshot.verified_by`, `verified_by_agency`, `verified_at`.
- `app/services/incident_notify.py` — the verified push names the team.
- `observer-web/src/pages/MonitoringPage.jsx` — verifier's organization.
- `MASTER_CONTEXT_v12.md` — §2.5.1 note on what is shown to whom.
- `pyproject.toml`, `uv.lock`, `app/core/config.py`, `admin-web/package.json`,
  `observer-web/package.json` — version 1.12.1.
- Tests: `tests/test_verifier.py` (new), `tests/test_tracking.py`,
  `tests/test_acceptances.py`.

### Database Changes
None. The organization was already recorded by every Verify since v11
(`area_acceptances.organization_id`); this version only reads it. The new query
was checked against the live schema (read-only `explain`).

### API Changes
| Endpoint | Change |
|---|---|
| `GET /incidents/{id}` (and every `IncidentDetail` response / `incident:` frame) | Adds `verified_by_organization`, `verified_by_agency`. |
| `GET /areas/{id}/tracking` and `track:<id>` frames | Adds `verified_by` (the team's display name, never a person), `verified_by_agency`, `verified_at`. |
| "Report verified" push and inbox row | Body names the team when known. |

All additions are optional fields; older apps ignore them.

### Frontend Changes
- Observer Console: verifier's organization. Admin Console unchanged — its
  Accepted list already showed agency, organization and name.
- Mobile (`replit-android` v1.12.1): see that repository's `CHANGELOG.md`.

### Testing
- Staff detail carries the verifier's name, organization and agency.
- The citizen's snapshot names the team, never the person; falls back to the
  agency, then "RepLiT Admin"; a new report has no verifier.
- The organization is the one recorded at verify time (query pinned).
- The verified push names the team and not the person; without a verifier it
  reads as before.
- Result: **377 backend tests pass**; `ruff` and `mypy --strict` clean; the
  Observer Console builds.

### Regression Check
Full backend suite passes. The two test fakes that answer the incident-detail
and snapshot reads were taught the one new query; no assertion was relaxed.
The snapshot still carries no user id, full name, phone or e-mail (existing
test, extended).

---

## v1.12.0 — 30 September 2026 — Verify and Respond separated; open to every responder and coordinator

### Changes

**Added**
- **Verify** as its own act: `POST /incidents/{id}/verify` moves an incident
  `reported → verified` and sends nobody (Master Context v12 §2.5.1).
- **Responders may verify**, as well as every Sub-Admin and Admin, so an
  incident never waits for one captain to be free.
- **Coordinators may respond**: any Fire Volunteer or BFP coordinator may
  respond to any verified fire their agency can see (§2.5.2), and share their
  location while they go.
- **Reject releases responders**: rejecting marks every active response
  `withdrawn` in the same transaction.
- **Master Context v12** (`MASTER_CONTEXT_v12.md`), recording the above.

**Modified**
- `POST /incidents/{id}/accept` is now the same act as `/verify` (the web
  consoles' button). The first no longer moves the incident to `en_route`.
- `POST /incidents/{id}/self-dispatch` ("Respond"): open to coordinators; the
  **first** respond moves `verified → en_route` — the moment the citizen sees
  "On the way" and gets the "Help is on the way" push. Later responders join
  without moving it.
- Reject is allowed from `reported`, `verified` **and `en_route`** (a mistaken
  verify can be undone after someone set off). From `arrived` it is still Fire
  Out with the false-alarm flag.
- Location streaming (`POST /incidents/{id}/location`, socket `location`) is
  accepted from whoever is responding, coordinators included.
- Web consoles: the Accept copy says it verifies (not "sends responders");
  action history labels `incident.verify` and `incident.en_route`.

**Fixed**
- Two taps on Respond at once returned a 500 (the partial unique index firing
  unhandled). It is now a 409 "You are already responding to this incident."
  The active-response check also runs again under the incident's row lock.

### Files Changed
- `app/services/incident.py` — `assert_can_verify` (replaces
  `assert_can_accept`), `can_respond`, `assert_can_respond`;
  `ALLOWED_TRANSITIONS` adds `en_route → rejected`.
- `app/api/routes/incidents.py` — verify (+ `/accept` alias), respond, reject,
  location; module authority notes.
- `app/api/routes/ws.py` — socket location from coordinators.
- `supabase/migrations/20260930120000_v12_verify_and_respond.sql` — new.
- `admin-web/src/pages/IncidentDesk.jsx`, `admin-web/src/pages/ActionRecord.jsx`,
  `admin-web/src/api/client.js`, `admin-web/src/lib/status.js`,
  `observer-web/src/pages/MonitoringPage.jsx`,
  `observer-web/src/pages/HistoryPage.jsx`, `observer-web/src/api/client.js`,
  `observer-web/src/lib/status.js` — copy and labels.
- `pyproject.toml`, `app/core/config.py`, `admin-web/package.json`,
  `observer-web/package.json` — version 1.12.0.
- `MASTER_CONTEXT_v12.md`, `CHANGELOG.md` — new.
- `tests/test_v12.py` — new; `tests/test_v10.py`, `tests/test_v11.py` — updated
  for the widened verify.

### Database Changes
- **Modified function** `public.enforce_incident_verification_authority()`:
  `verified_by` may now be a `response_team` user (previously `admin` or
  `sub_admin` only). Citizens still cannot verify; `verified_by` stays mandatory.
- No new tables, columns, constraints or indexes. The existing partial unique
  index `dispatch_logs_active_uniq (responder_id, area_id) where status =
  'active'` is what stops anyone responding to the same incident twice.
- **Migration requirement**: apply `20260930120000_v12_verify_and_respond.sql`
  (`npx supabase db push`) **before** deploying this backend; otherwise a
  responder's verify is refused by the database. It changes no data and is
  reversible by re-running the v11 function definition.

### API Changes
| Endpoint | Change |
|---|---|
| `POST /incidents/{id}/verify` | **New.** Verify; returns `IncidentDetail`. Staff (`admin`, `sub_admin`, `response_team`) scoped by agency visibility. 409 for a responder when already verified ("respond instead"). |
| `POST /incidents/{id}/accept` | Same handler as `/verify`. First press → `verified` (was `en_route`). Later captains' presses record participation as before. |
| `POST /incidents/{id}/self-dispatch` | Authorization widened to Fire Volunteer / BFP sub-admins; observers and Admin get 403. First respond moves `verified → en_route`. 409 when already responding (also under a race). 409 "Verify this incident before responding" from `reported`. |
| `POST /incidents/{id}/reject` | Allowed from `en_route`; releases active responses (`responders_released` in the audit metadata). |
| `POST /incidents/{id}/location` | Accepted from coordinators with an active response. |
| Socket `location` action | Same widening. |

Audit actions: new `incident.verify` (first verify) and `incident.en_route`
(first respond). Broadcast event types: `incident_verified` (first verify),
`incident_en_route` (first respond), `responder_dispatched` (later responders).

### Frontend Changes
- Web: Admin Incident Desk and Observer Monitoring (Accept copy), Admin Action
  Record and Observer History (labels).
- Mobile (`replit-android` v1.12.0): see that repository's `CHANGELOG.md` —
  Verify / Respond / Reject controls, zoomable report photo, routing to the
  fire, live staff screens.

### Testing
- **Incident verification** — first verify moves only to `verified`; responder,
  captain, Admin may verify; citizen 403; second captain records participation;
  responder told to respond (`tests/test_v12.py`).
- **Incident acceptance / response** — respond refused before verify; first
  respond → `en_route` with the reporter's push event; later responders join;
  any Fire Volunteer / BFP coordinator may respond; observer, Admin, citizen 403.
- **Multiple users on one incident** — same person twice → 409; a race the
  pre-check misses → the unique index's 409, nothing left behind.
- **Coordinator rejection** — from `verified`; from `en_route` releasing every
  responder; not from `arrived`; responders and citizens 403.
- **Citizen "On the way"** — asserted through the `incident_en_route` event on
  the first respond (the push and the Track It Live status both key on it).
- **Real-time status updates** — every change still goes through
  `finish_incident_change` (socket broadcast to `incident:` and `agency:`),
  unchanged and covered by the existing suites.
- **Permission/authorization** — the above, plus the database pin (migration).
- **GPS location** — a responding coordinator may stream; an observer may not.
- Result: **370 backend tests pass**; `ruff` and `mypy --strict` clean; both
  web consoles build.

### Regression Check
- The full backend suite (auth, phone OTP, reports, clustering, tracking, live
  map, Post-Incident Report, alarms, audit) passes unchanged apart from the two
  v11 tests that pinned the old "Accept moves to en_route" rule, which were
  updated deliberately.
- Observer web flow unchanged in shape: an Observer's Accept still verifies a
  new incident or records participation.
- Citizen app and API unchanged.
