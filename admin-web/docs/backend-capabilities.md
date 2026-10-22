# Admin redesign: backend capabilities

Source: `origin/main` at `d1a343c` (API v1.12.8), audited against PRD v13 and the
19 October 2026 frontend implementation brief. This is a contract reference,
not authorization to add integrations or a claim that the backend
already implements v13. Keep request payloads and status values compatible with
the API. Do not fabricate missing fields, records, successful actions or permissions.

## Identity and permission boundaries

- The console admits `role === 'admin'`. Coordinators are `sub_admin`, Responders
  are `response_team`, and Citizens are `general_user`.
- `GET /auth/me` supplies `id`, `email`, `full_name`, `role`, `agency_type`,
  `primary_org_id`, verification fields and basic profile fields. It supplies no
  `org_role`, central-hub flag, AFK flag, first-sign-in flag or permission list.
- Resolve the user's organization through `primary_org_id` and `GET /organizations`.
  Current Admin schema/database constraints expect `agency_type` to be empty;
  the organization's `agency_type` is useful for display and UI predicates.
- Verification/Affiliates are central-hub-only in the design, but the API allows
  every Admin. An authoritative hub capability is missing. Do not infer hub
  authority from an email, organization name, or absent organization. Prepare
  Central/Standard variants with explicit capability inputs and preserve current
  authorization until the product/backend decision is available.
- Admin reads and incident authority are currently global. Own-organization UI
  restrictions improve presentation but cannot supply missing server isolation.

## Destination mapping

| Screens | Supported calls and data | Restrictions / omitted controls |
|---|---|---|
| A01–A02b: sign in | `POST /auth/login` with `{email,password}`; `GET /auth/me`; `POST /auth/logout`. Forgot-password: `POST /auth/recover` with `{email}`. | Keep Admin-only admission. Recovery has a backend-hosted `GET /auth/reset-password` page; its POST accepts `{access_token,password}`. |
| A03–A04: affiliation | Public `POST /affiliates/register`: `organization_name`, `agency_type`, `contact_email`, optional `contact_phone`, `address`, `roster[{full_name,role}]`, `equipment[{name,type}]`, `sec_certificate_name`. | Certificate field is a filename, not an uploaded file. No Admin-prefix/password registration exists here. |
| A05–A06c: affiliate review | `GET /affiliates?status=pending\|approved\|rejected`; `POST /affiliates/{id}/accept` or `/reject` with `{notes}`. | Pending requests only. Acceptance creates the organization and provisions a **Coordinator (`sub_admin`)**, using the contact email. It does not create a v13 Admin or send the new Admin-registration link. Show actual `account_provisioned`, `account_created`, `invite_email_sent`, `account_email` and `detail` from the result. |
| A07–A11: Admin registration | None. | No one-time registration-token validation, prefix availability, `.admin@replit.com` registration or registration submission. Omit these actions. |
| A12: first sign-in | Existing authenticated profile and local presentation. | No server onboarding-completion/first-sign-in state. |
| A20–A21, A83: dashboard | `GET /incidents/stats`; `GET /incidents?limit=200`; existing live-feed polling and local sounds. Counters include `active_incidents`, `pending_verify`, `units_deployed`, `units_standby`, `pending_reports`. | Admin counters are global. No organization availability data for A72. |
| A22–A26, A80–A82, A84: incidents | `GET /incidents` supports `active_only`, `status`, `limit` (1–500), `offset`; detail `/incidents/{id}`; evidence `/reports`; assignments `/dispatches`. `POST /incidents/{id}/accept` is available to Admin. | Search is client-side unless all needed pages are loaded. Acceptance is legacy `reported → verified`; it dispatches nobody. Admin cannot self-dispatch. Omit Admin rejection per the brief even though `/reject` exists. No structured on-scene fire classification or Admin water/backup action. |
| A27–A27b: merge | `GET /areas/overlaps/pending`; `POST /areas/overlaps/{overlap_id}/merge` or `/keep-separate`, no body. Pending rows give both IDs/designations, distance and expiry. | Merge window is 120 seconds. Direction is fixed: B is absorbed into A. Dropped B must allow a transition to `merged` (`reported` or `verified`). Do not offer arbitrary incident-pair merging or pretend the retained Area can be selected. Main records these decisions in audit logs. |
| A28: declined | None. | `declined` is not a supported Area status. Do not send it as a status filter or relabel an existing `rejected` incident as Declined. |
| A30–A31: live map | Existing incident feed or `GET /areas`; map layers below. Actual positions: `GET /incidents/{id}/responders/locations`; names/organizations from `/dispatches`. `GET /areas/{id}/tracking` also supplies a tracking snapshot where authorized. | No guaranteed own-org vehicle filtering at the API. Do not draw invented vehicle positions. |
| A40–A42: Requests | `GET /alarm-requests?status=&area_id=` is readable by Admin; `GET /alarm-requests/mine` lists the caller's sent alarm requests. Rows include Area/designation, requester/name, proposed level, justification, status, reviewer notes/times. | These are **alarm requests only**, not the v13 Admin-to-Admin inbox. No generic water/equipment/backup messages or acknowledgement/reply endpoint. |
| A43–A46b: water, backup, alarm actions | Existing alarm POST/execute/reject routes are not usable by Admin accounts. | Creation requires FV/BFP Coordinator, or FV Responder. Execute/reject requires `sub_admin` + `agency_type === 'bfp'`. A BFP organization's **Admin** still fails that check. Omit send/execute/decline actions from this console. Task Force levels are absent. |
| A32–A34b: water resources | `GET /map/hydrants`, `/map/bodies-of-water`, `/map/underground-cisterns`, and `/{id}` details. Admin `DELETE /map/{type}/{id}` returns 204. Other existing layers: `/map/evacuation-sites`, `/map/risk-zones`. | Separate legacy resource tables; no `water_level_pct`, 5% updates or water-resource history endpoint. Show actual status/capacity fields, never an invented percentage. Ground-truth override is FV Coordinator-only. |
| A35: add/update resource | Legacy Admin POST/PATCH CRUD exists for the map layer types. | The brief explicitly blocks A35. Leave add/update controls out despite these older endpoints. |
| A47: organization | `GET /organizations`; `GET /organizations/{id}/personnel`; `GET /equipment?organization_id={id}`. Org fields: name, agency, description, contacts, address, active flag, personnel/equipment counts. | No organization editing, AFK, availability or Admin-owner endpoint. Select own organization from `primary_org_id`; preserve existing directory access where required. |
| A48–A49b: accounts | Read roster from `/organizations/{id}/personnel`; filter `role === 'sub_admin'` for Coordinators. `POST /admin/users` accepts `{email,password,full_name,role:'sub_admin',agency_type,primary_org_id}`. | Fix role and own org in the UI. No Coordinator reset/deactivate/edit endpoint for Admin. `/team/responders` management is Coordinator-only. Personnel reads omit email, session state and last-active time; do not invent these columns' values. No automatic Coordinator email-prefix or generated-password service. |
| A50–A51: verification | `GET /admin/verifications/pending` returns identity, channel/status/provider, submission time and signed `id_image_url`/`selfie_image_url`. `POST /admin/verifications/{id}/approve`; `/reject` with `{notes}`. | Manual-review records only. No ID-number field or separate unmask endpoint. Apply design masking to supplied data. Central-hub restriction is not enforced by the backend. |
| A60–A63b: reports and summaries | `GET /post-incident-reports?area_id=&limit=&offset=`; `/incidents/{id}/post-incident-report` and plural `/post-incident-reports`; `/incidents/{id}/summaries`; `GET /ai-summaries?limit=`. PDF: `GET /incidents/{id}/report.pdf` with bearer auth; `POST /incidents/{id}/report-link` returns a five-minute signed download path. | Stored AI summaries are not immutable standalone CIAR records. Display real PIR fields and summary text; no fabricated six-part CIAR. Summary-list state is `ready`, `writing`, or `unavailable`; absent summaries are not proof of a specific provider failure. No regenerate/retry action per the brief. |
| A64–A66: audit/corrections | `GET /audit-logs` supports `action`, `entity_type`, `area_id`, `actor_user_id`, `limit` (≤500), `offset`. Entries contain actor snapshots, action, before/after, metadata and time. | Audit is read-only. No correction-creation POST; omit A65/A66 save actions. No `entity_id` query filter: a resource-specific history derived from a page of logs is partial and must not be presented as a complete water-resource history. |
| A70–A72: settings/availability | Existing browser-local sound/category mute, repeat/desktop notification and theme preferences. | No AFK/availability endpoint or returned org availability. Omit the toggle and invented AFK states. |
| A85: sidebar rail | Responsive client layout. | No API dependency. |

## Data and behavior details

**Two different acknowledgements:** `useLiveFeed().acknowledge(id)` records that
this browser has viewed an alarm and silences its repeat sound. It does not send
an incident lifecycle mutation. `POST /incidents/{id}/accept` writes a server
acceptance and may move the incident from `reported` to `verified`; it does not
dispatch a crew. Keep those operations distinct even when both use human wording
such as “acknowledge.”

**Statuses:** API lifecycle values remain `reported`, `verified`, `en_route`,
`arrived`, `fire_out`, `post_incident_report`, `closed`, `rejected`, `merged`.
The console labels `verified` as "Acknowledged": PRD v13 §4.5 renames the label
of the same act, and `src/lib/status.js` records it. Filters and requests still
send `verified`. `rejected` is never shown as "Declined"; a `declined` value is
drawn only if the server starts sending one. Identity verification keeps
"Verified".

**Resources:** hydrants expose `bfp_status`, `ground_truth_status`,
`effective_status`, who/when checked, notes, coordinates and address. Valid legacy
status values are `operational`, `non_operational`, `under_maintenance`, `unknown`.
Bodies of water and cisterns have their own schemas; they do not expose the new
uniform water-level model. The existing Admin map CRUD and delete calls must not
be silently repurposed as percentage management.

**Reports:** origin/main adds participation checks for non-Admins reading PIRs,
summaries and PDFs; Admin remains permitted to read all. PIR submission schedules
AI summarization and additional teams' reports can produce newer summaries.
`GET /ai-summaries` may schedule missing-summary backfill; its returned state is
the supported source for generating/unavailable panels. There is no CIAR-specific
immutable identifier, correction workflow or provider-error detail endpoint.

**Live behavior:** preserve the existing 12-second feed refresh and alarm settings.
Real empty responses, request failures and pending loads require distinct states;
never convert a failed fetch into a successful empty list. A map or photo loading
failure is likewise not evidence that its underlying record does not exist.
