# RepLiT Master Context Document — v11.0

**Report Location and Incident In Time**
An Area-Based GPS Clustering and Progressive User Verification System for Fire
Volunteer Organizations in Pasay City

| | |
|---|---|
| **Document version** | 11.0 |
| **Last updated** | 21 September 2026 |
| **Development team** | M2STZ |
| **Adviser** | Mr. Carlito L. Cunanan, MIT |
| **Institution** | National Teachers College |
| **Supersedes** | v10.0 (8 September 2026) |

---

## VERSION HISTORY

| Version | Date | Changes |
|---|---|---|
| v7.0 | April 2026 | Removed triangulation, added GPS clustering, added AI vision analysis |
| v8.0 | 17 May 2026 | Removed AI vision analysis; added Progressive User Verification, Crowdsourced Neighborhood Notification (300 m), Area-Based GPS Clustering with versioning |
| v9.0 | 7 Sep 2026 | First version written against the built system rather than the plan. Added Coordinator/Observer authority model, design system, Area merge lifecycle |
| v10.0 | 8 Sep 2026 | Applied Sir Carlito's insights from Meeting 12. Introduced Observer web surface, formalised four-tier hierarchy, added Post-Incident Report, per-agency notification sounds, Admin routing role |
| **v11.0** | **8 Sep 2026** | **Simplifies the incident lifecycle.** Accept collapses `verified` and `dispatched` into a single act available to Admin, Coordinators and Observers. The `dispatched` step is removed. Vehicle and roster selection move from dispatch time into the Post-Incident audit between Fire Out and Closed. Admin's manual routing is removed — the reporter's agency selection determines who sees the incident. Status labels rename to the operator-facing set: Reported, Verified, En Route, Arrived, Fire Out, Closed. |

### What changed from v10

**Removed**

- **The `dispatched` step** and everything it carried. Choosing a truck and roster at dispatch time was the single largest source of paperwork during a live incident. Deleting the step means responders can go the instant Accept fires.
- **Admin's manual routing** (v10 §2.6.2). The reporter's `selected_agencies` already carries the intent; Admin re-selecting the same list was busywork. Whichever agency the reporter chose sees the incident on their surface and can Accept it themselves.
- **Fire-Volunteer-only `verify` restriction**. In v9 and v10 only a Fire Volunteer Sub-Admin could verify. In v11 the Accept action is the verify action, and it is available to Admin, Coordinators and Observers alike, first-to-Accept wins.

**Changed**

- **Lifecycle labels** rename at the schema level (§2.5). `pending → reported`, `resolved → fire_out`. The `arrived` label is kept as-is despite Meeting 12 suggesting "On Scene," at team preference. The `verified` and `closed` labels are unchanged.
- **First Accept transitions the Area to `verified` and immediately to `en_route`** (§2.5). A second and third Accept from other responding agencies is an acknowledgment for that agency's own participation — it is logged but does not move the Area again.
- **Reject remains Coordinator-only** (Fire Volunteer + BFP mobile Sub-Admins), unchanged from v10.
- **Post-Incident Report** (v10 §2.5) is preserved and kept as the name of the audit step between `fire_out` and `closed`. Fields unchanged: truck, driver, roster, equipment, notes.
- **Filed by the primary team captain only** — the Fire Volunteer coordinator whose team responded. Other agencies (Medical, Police, Barangay) do not file separate Post-Incident Reports in v11. This resolves the "who blocks Closed" question by keeping the filer single.

**Added**

- **False-alarm handling on scene** (§2.5). If a team reaches `arrived` and finds nothing — prank, already-out fire, wrong address — the team captain marks the Post-Incident Report with a "false alarm" flag and the audit records why. `fire_out → closed` proceeds normally with the flag set.

**Not built, and honestly recorded as such** — §10.3.

---

## 1. SYSTEM OVERVIEW

### 1.1 Project Description

RepLiT is an emergency reporting and coordination platform for Fire Volunteer
organisations. A resident reports an incident from a phone; reports made close
together in space and time are clustered automatically into a single **Area**;
whichever responding agency Accepts first flips the Area to Verified and En
Route in a single act; responders advance the incident from their own phones;
every consequential action is written to an append-only record; and once the
fire is out, the responding team captain files a Post-Incident Report from
memory of the scene rather than during it.

The three original claims from v8 still hold, and all three are implemented:

1. **Progressive User Verification** — a credibility score attached to each
   reporter, so a dispatcher can weigh an unverified source differently from a
   known one without ignoring either.
2. **Crowdsourced Neighborhood Notification** — residents within 300 m of a
   new report are asked whether they see it too, so corroboration is gathered
   from people who are already there.
3. **Area-Based GPS Clustering** — many reports of one fire become one
   incident, rather than several competing ones.

### 1.2 Operational Context

Pasay City, Metro Manila. The primary operator is a Fire Volunteer brigade
working alongside the Bureau of Fire Protection, with police, medical and
barangay personnel participating for situational awareness through the
Observer web surface.

Default map centre: **14.5378° N, 121.0014° E**.

### 1.3 Problem Statement

1. Duplicate reports of the same fire arriving as separate incidents
2. No way to judge whether a report is credible before committing units
3. False alarms consuming trucks that another emergency needs
4. No shared live picture of what is happening across the city
5. Coordination between agencies happening by phone call and memory
6. No durable record of who decided what, or when
7. Agencies that should only observe were able to act — closed by v9 §2.6
8. Time-consuming post-response paperwork happening during the response,
   slowing units on scene — closed by v10 §2.5 (Post-Incident Report)
9. Observers needed a stationed view of the picture, not a field view —
   closed by v10 §2.6 (Observer web surface)
10. The verify-then-dispatch two-step made responders wait for coordinator
    availability before rolling — closed by v11 §2.5 (Accept collapses both)

---

## 2. CORE FEATURES

### 2.1 Progressive User Verification

A user's `verified_percent` is the sum of the channels they have completed:

| Channel | Award | Mechanism |
|---|---|---|
| Mobile number | **+40%** | SMS one-time code |
| National ID | **+50%** | Photograph of the ID and a matching selfie, reviewed by an Admin |
| Email address | **+10%** | Confirmation link |

**Total: 100%.**

A badge is derived from the total by a database trigger — never computed on a
client:

| Badge | Range |
|---|---|
| `yellow` | < 50% |
| `light_green` | 50–89% |
| `green` | 90–99% |
| `green_check` | 100% |

National ID capture is camera-only by design. Neither the ID nor the selfie
may be chosen from the gallery — a live capture forces physical possession of
the document, and it is what makes the paired selfie mean anything.

Verification level is **advisory, never gating**. It is shown to whoever is
reviewing a report. It does not slow an incident down, and no report is
refused for a low score.

### 2.2 Crowdsourced Neighborhood Notification

When a report creates or joins an Area, every user whose last known location
is within **300 m** is notified and asked one question: do you see it too?

- **Report** — corroborates. The neighbour is taken into the SOS flow so their
  confirmation becomes a real report with its own photo and GPS.
- **Ignore** — dismisses, and suppresses further alerts for that Area.

Frequency and volume caps prevent an incident from becoming a nuisance.

### 2.3 Area-Based GPS Clustering

A submitted report is resolved against existing Areas in this order:

1. An **active** Area within **300 m** whose last activity is under **5
   minutes** old → the report joins it.
2. Otherwise, a same-location Area (within 300 m) updated under **1 hour** ago
   → a **new version** is created (`Area 1.2`), chained to its parent.
3. Otherwise → a **new Area**.

**Confidence score** is recomputed on every join:

```
confidence = 0.4·N + 0.3·S + 0.3·V

N = min(report_count / 10, 1)             corroboration
S = max(0, 1 − σ / 300 m)                 spatial agreement
V = mean(reporter verified_percent) / 100 source credibility
```

Banded into `low` / `medium` / `high`.

> **Operational note.** Because V is one third of the weight and phone
> verification has never succeeded (§10.3), every Area's confidence is
> currently capped below the `high` band. This is a configuration problem,
> not a formula problem.

**Overlaps.** When two Areas grow within range of one another, a pending
overlap is raised for a coordinator to decide: **merge** or **keep separate**.
A merged Area takes the terminal status `merged` and records `merged_into_id`.

### 2.4 Real-Time GIS Visualisation

Layers available to a signed-in user:

| Layer | Source | Audience |
|---|---|---|
| Incident areas | `GET /areas` | Everyone |
| Evacuation sites (shelters) | `GET /map/evacuation-sites` | Everyone |
| Fire hydrants | `GET /map/hydrants` | Everyone |
| Risk zones | `GET /map/risk-zones` | Everyone |
| Bodies of water | `GET /map/bodies-of-water` | Everyone |
| Underground cisterns | `GET /map/cisterns` | Everyone |

**A boundary worth stating.** `GET /incidents` is staff-only — it carries
agency scoping and Post-Incident detail. The citizen map draws `GET /areas`,
which gives the incident, its status, confidence and report count, but not who
is responding.

**Evacuation sites may sit outside Pasay.** A fire inside Pasay may need a
shelter in Parañaque, Makati or elsewhere in Metro Manila. Sites outside
Pasay are drawn with a distinct marker.

Fire and police station markers are a static reference list held in the app
(`lib/models/facility.dart`).

### 2.5 Incident Lifecycle — *significant change in v11*

```
reported → verified → en_route → arrived → fire_out → post_incident_report → closed
     ↓                                                                          
  rejected                                                                     
              (terminal)                                                        

  merged                                                                        
              (terminal)                                                        
```

Every transition is validated server-side by `assert_transition`. A client
cannot skip a stage.

#### 2.5.1 Accept — the collapsed act

**First Accept transitions `reported → verified → en_route` in a single
step.** The Accept control is available to:

- **Admin** (web) — on any Area
- **Coordinator Sub-Admin** — on Areas whose `selected_agencies` includes
  their agency (`fire_volunteer`, `bfp`)
- **Observer Sub-Admin** — on Areas whose `selected_agencies` includes their
  agency (`police`, `medical`, `barangay`)

The **first** Accept wins — it is the one that moves the Area to `verified`
and immediately to `en_route`. It is written to `audit_logs` with the actor's
role and agency.

Subsequent Accepts from other responding agencies are **participation
acknowledgments only**. They are written to `audit_logs` but do not change
the Area's status again. Each agency's UI reflects its own accepted state so
operators can see whether their team is committed.

#### 2.5.2 Reject — Coordinator-only

Unchanged from v10. Only a Fire Volunteer or BFP Sub-Admin may reject an
Area. Observers cannot reject, and neither can Admin — Admin's Accept is a
router-like act, not a judgment on credibility. The 403 message for an
observer attempting a reject is the same as in v9 and v10:

> *"Your agency takes part for situational awareness only, so it cannot
> reject incidents. Fire Volunteer or BFP coordinators handle this."*

An Admin attempting a reject sees a comparable 403 explaining that credibility
judgments belong to the coordinators in the field.

#### 2.5.3 Arrived, Fire Out, Post-Incident Report, Closed

Responders advance the Area from `en_route` to `arrived` by tapping Arrived
on their mobile client. The team captain marks `fire_out` when the fire is
out.

**Post-Incident Report** sits between `fire_out` and terminal `closed`. It is
filed by the **primary team captain** — the Fire Volunteer Sub-Admin whose
team responded — and captures:

| Field | Notes |
|---|---|
| Truck ID and type | Which vehicle was used |
| Driver name | |
| Responder roster | Who actually went |
| Equipment taken | From the unit |
| Coordinator notes | Free text |
| **False-alarm flag** | *new in v11* — set when the team reached `arrived` and found nothing (prank, already-out fire, wrong address). Required narrative if set. |

**Submission rule.** The form is single-submit: it saves once fully filled.
There is no draft state. The `fire_out → closed` transition is blocked until
submission succeeds, so no incident becomes terminal without its record.

**Other responding agencies do not file separate Post-Incident Reports in
v11.** Medical, Police and Barangay activity is captured in their own
`audit_logs` entries (each Accept, each status change), which is sufficient
for situational awareness without adding filing burden.

#### 2.5.4 Terminal states

`rejected`, `merged` and `closed` are terminal and leave the live feed
(`TERMINAL_STATUSES` in `app/services/incident.py`). `rejected` and `merged`
cannot be versioned.

### 2.6 Role-Governed Access Control — Four-Tier Hierarchy

The schema `user_role` enum is unchanged from v9 — `admin`, `sub_admin`,
`response_team`, `general_user` — so existing code and migrations remain
valid. The tier names are the human-facing description.

| Tier | Name | Platform | Agencies | Notes |
|---|---|---|---|---|
| 1 | **Admin** | Web (Admin Console) | — | Can Accept any Area; cannot reject |
| 2 | **Sub-Admin (team captain)** | Mobile OR Web (see below) | fire_volunteer, bfp, police, medical, barangay | Coordinator vs Observer split, §2.6.1 |
| 3 | **Response Team** (members) | Mobile | All five | Executes the response |
| 4 | **Citizen** | Mobile | — | Reports incidents; may be asked to corroborate |

**Platform is driven by device and role, not agency.**

- A team captain who has a device and is assigned an observer role → **web**
  (Observer Console, §3.1).
- Otherwise → **mobile**.

In practice this places Fire Volunteer and BFP team captains on mobile
(Coordinators, working the response), and Medical, Police and Barangay team
captains on web (Observers, stationed and watching).

Response Team members remain on mobile across all five agencies.

#### 2.6.1 Coordinator vs Observer

Access is the product of two enumerations:

- `user_role` — `admin`, `sub_admin`, `response_team`, `general_user`
- `agency_type` — `fire_volunteer`, `bfp`, `police`, `medical`, `barangay`

A Sub-Admin's authority depends on their agency:

| Class | Agencies | Platform | May |
|---|---|---|---|
| **Coordinator** | `fire_volunteer`, `bfp` | Mobile | **Accept**, reject, mark fire out, file Post-Incident Report, withdraw participation, press fire codes |
| **Observer** | `police`, `medical`, `barangay` | Web | **Accept** (participation acknowledgment or first-Accept verify), see incidents that requested their agency |

**Where enforcement lives.** `assert_coordinator()` in
`app/services/incident.py` guards reject and Post-Incident Report; the Accept
route accepts all three tiers (Admin, Coordinator, Observer) but scopes
Observer access to their own `selected_agencies`. UI predicates mirror the
server (`admin-web/src/auth.jsx`, `observer-web/src/auth.jsx`).
**The UI mirror is a courtesy; the server is the authority.**

**Observer navigation is three items only** — Dashboard, Map (Monitoring),
Audit Log (History). Equipment, Affiliate Organization and Account
Management are Admin and Coordinator concerns.

Visibility remains scoped by `reports.selected_agencies` — an observer sees
the incidents where a reporter asked for their agency, and no others.

#### 2.6.2 Admin — Acceptor, not Router

Admin (Barangay 76 web) can Accept any Area. Admin does **not** route in v11:
the reporter's `selected_agencies` already carries the intent, and each
selected agency's surface displays the Area with its own Accept button.
Admin's Accept is available as a safety net — for cases where the Fire
Volunteer coordinator is offline and Observers are on the fence, so the Area
does not sit unaccepted while a fire grows. Every Admin Accept is logged.

### 2.7 Design System

Both web front-ends and the mobile app implement Claude Design hand-offs:
**General User App v2** (mobile), **Admin Console** (web), and the
**Observer Console** (web).

| Token | Value | Use |
|---|---|---|
| Ground | `#131313` | Every screen |
| Canvas | `#0B0B0B` | Outside the phone frame; behind a camera viewfinder |
| Surface | `rgba(38,38,38,.54)` | Cards and rows — translucent, never a lighter solid |
| Hairline | `rgba(72,72,71,.35)` | Every card edge. **No drop shadows.** |
| Accent | `#FF9066` → `#FF7943` | The only accent |
| On-accent | `#581A00` | Text on the coral gradient — dark brown, not black |
| Live / destructive | `#FF544E` | |
| Settled | `#22C55E` | |

**Glow appears in exactly two places:** the splash mark and the SOS button.

**The text logo has no light-ground variant yet.** The wordmark was drawn for
the dark ground and is light-on-dark; now that a light ground exists as a token
override (§2.7, the in-app switch), it needs a dark-on-light counterpart chosen
by the same token rather than recoloured at the call site. Not built — §10.3.

Radii: 11 chip · 12 control · 14 card · 16 panel · 20 sheet.

Type: `w900` uppercase names a thing; `w300` is prose; a 10 px `w700`
uppercase "eyebrow" labels every section.

Tokens live in `lib/theme.dart`, `admin-web/src/index.css` and
`observer-web/src/index.css`. Repeated shapes live in
`lib/widgets/design.dart`.

#### 2.7.1 The rule the implementation follows

**Never build an interface the backend cannot honour.** Where the design
shows something with no data behind it, it is left out and the reason
recorded in a code comment.

| Design element | Why it is absent |
|---|---|
| Console "Acceptance %" | No such metric exists |
| Suspend / Revoke organisation | No endpoint mutates an organisation |
| Mobile "Skip the photo" | The server rejects a report without one |
| Voice-note recorder | No endpoint accepts audio |
| Sign-up OTP box | Sign-up is email + password; phone is a later step |
| "Avg arrival" statistic | `/reports/mine` carries no dispatch timestamps |
| Hash-chained audit digest | `audit_logs` has no hash column — claiming it would be a fabricated security property |
| **Manual dispatch UI** *(v11)* | Dispatch was removed — a UI for choosing truck and roster at dispatch time was drafted, then dropped when the step was |

### 2.8 Notification Sounds

Per-agency audio cues distinguish incident category at a glance without
requiring the operator to look at the screen. The Admin Console and the
Observer Console both play them; the mobile app is silent on inbound.

| Category | Placeholder cue | Where it plays |
|---|---|---|
| Fire (fire_volunteer, bfp) | placeholder cue TBD | Admin Console |
| Police | *"mamang pulis, tulong!"* | Admin Console; Police Observer Console |
| Medical | *"doc, doc, tulong!"* | Admin Console; Medical Observer Console |
| Barangay | *"bakbak kol!"* | Admin Console; Barangay Observer Console |

**Placeholder cues only.** The final audio is not selected. Selection happens
with the client during pilot.

**General User side.** The citizen app plays a short *"salamat!"* cue when a
report submits successfully. Placeholder text — the final audio is likewise
TBD.

**Controls.** Users can turn sounds off in settings. Per-category volume is
available; muting the category mutes only that stream.

### 2.9 Admin Console Enhancements

- **Red count badge** on incident-related menu items and cards, showing the
  number of new items since the operator last viewed that surface.
- **Notification sounds** per §2.8.
- **Clickable incident cards** on the dashboard — a card taps through to the
  incident detail directly.

### 2.10 Language and Reading Level — *planned, not built*

The citizen app is written in English at roughly B2: full sentences, subordinate
clauses, and words like "corroborate", "credibility" and "discrepancy". That is
the register the team writes in, not the register Pasay residents read under
stress at two in the morning.

Two changes follow from that, neither of them started:

- **Drop the citizen app to CEFR A2.** Short sentences, common words, one idea
  per line. A2 is the level a reader with elementary English handles without
  effort — which is the point, because the app is read while something is on
  fire. This covers the citizen surface only: the Admin and Observer consoles
  and the coordinator screens are used by trained staff and stay as they are.
- **Add Tagalog.** English-only is a real barrier for the people the system is
  for. Tagalog is the language most Pasay residents would choose for an
  emergency, and an emergency app that is harder to read than the emergency is
  not doing its job. Scope is the citizen surface: SOS, report status, live
  tracking, neighbour alerts, verification and the help centre.

Neither has a delivery date, and §10.3 records both as open. Nothing about the
lifecycle, clustering or verification changes — this is presentation only.

---

## 3. TECHNICAL ARCHITECTURE

### 3.1 Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI · asyncpg · Pydantic v2 · structlog · Python 3.14 · `uv` |
| **Database** | Supabase — PostgreSQL 17.6 with PostGIS 3.3.7 |
| **Auth** | Supabase GoTrue (JWT, validated against project JWKS) |
| **Storage** | Supabase Storage — private buckets for report photos and national IDs |
| **Admin Console** | React 18 · Vite · react-leaflet — a separate SPA |
| **Observer Console** | React 18 · Vite · react-leaflet — a separate SPA |
| **Mobile** | Flutter (Dart SDK ^3.11.1) · flutter_map · geolocator · camera · image_picker · firebase_messaging |
| **Push** | Firebase Cloud Messaging |
| **Basemap** | Mapbox `dark-v11` raster tiles, OpenStreetMap fallback |
| **SMS** | *In search of a provider — see §10.3* |

### 3.2 System Architecture

```
┌───────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Mobile (Flutter)  │    │ Admin Console    │    │ Observer Console │
│ 4 tiers:          │    │ (React + Vite)   │    │ (React + Vite)   │
│ Sub-Admin coord., │    │ Admin only       │    │ Observer         │
│ Response Team,    │    │                  │    │ sub-admins only  │
│ Citizen           │    │                  │    │                  │
└────────┬──────────┘    └────────┬─────────┘    └────────┬─────────┘
         │        HTTPS / JWT     │                       │
         └────────────────────────┼───────────────────────┘
                                  ▼
                        ┌───────────────────┐
                        │   FastAPI         │
                        └─────────┬─────────┘
                                  │ asyncpg
                                  ▼
                   ┌──────────────────────────────┐
                   │ Supabase                     │
                   │  PostgreSQL 17.6 + PostGIS   │
                   │  GoTrue · Storage · Realtime │
                   └──────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
               Firebase FCM              SMS provider (TBD)
```

### 3.3 Data Flow — End to End

1. **Capture** — resident holds SOS 3 s → GPS fix → chooses agencies →
   photographs the scene → `POST /reports/submit` (multipart)
2. **Cross-reference** — server compares the photo's EXIF GPS against the
   device fix; a discrepancy over 100 m flags the report for closer review
   but does not reject it
3. **Cluster** — §2.3 resolves the report to an Area and recomputes
   confidence
4. **Notify** — residents within 300 m are asked to corroborate; requested
   agencies see the new Area on their surface with an Accept control
5. **Summarise** — a background job writes a text summary for whoever is
   reviewing
6. **Accept** — the first Admin / Coordinator / Observer to press Accept
   moves the Area `reported → verified → en_route` in one step. Subsequent
   Accepts by other agencies are participation acknowledgments and are
   logged separately.
7. **Advance** — responders tap Arrived on the mobile client; team captain
   marks Fire Out when the fire is out
8. **Post-Incident Report** — the primary team captain (Fire Volunteer)
   files truck, driver, roster, equipment, notes, and the false-alarm flag
   if applicable. The `fire_out → closed` transition is blocked until this
   is submitted.
9. **Audit** — every step appended to `audit_logs` with the actor's role
   and agency *as they were at the time*

---

## 4. DATABASE SCHEMA

**Migrations grow to ~21 with v11.** The v11 migration renames
`area_status` values (`pending → reported`, `resolved → fire_out`) and adds
the `false_alarm` boolean column to `post_incident_reports`. `dispatch_logs`
is retained but no longer written; a follow-up migration will drop it once
no code path reads it.

### 4.1 Core Tables

| Table | Holds |
|---|---|
| `users` | One row per auth user; role, agency, `verified_percent`, derived `badge`, last known location |
| `organizations` | Accredited agencies |
| `affiliate_requests` | Organisation onboarding queue |
| `reports` | Individual submissions — device GPS, photo, EXIF flags, `selected_agencies` |
| `areas` | Incident clusters — centroid, status, confidence and its N/S/V components, alarm level, version chain, `merged_into_id` |
| `area_reports` | Which reports belong to which Area |
| `area_overlaps` | Pending merge / keep-separate decisions |
| `area_acceptances` *(new in v11)* | One row per Accept per Area — actor, agency, whether it was the first (verifying) Accept |
| `user_verifications` | One row per channel per user |
| `dispatch_logs` | *v11: retained but no longer written; to be dropped after code stops referencing it* |
| `post_incident_reports` | One row per Area — truck, driver, roster, equipment, notes, `false_alarm` boolean; foreign-keyed to the filer |
| `audit_logs` | Append-only record — actor, role and agency at the time, before/after state, IP, request id |

### 4.2 Supporting Tables

`org_roster` · `equipment` · `responder_locations` · `fire_codes` ·
`fire_code_events` · `alarm_requests` · `neighborhood_notifications` ·
`notification_log` · `device_tokens` · `ai_summaries` ·
`password_reset_tokens` · `map_layer_update_requests`

**Map layers:** `hydrants` · `evacuation_sites` · `risk_zones` ·
`bodies_of_water` · `underground_cisterns`

### 4.3 Enumerated Types

`user_role` · `agency_type` · `area_status` · `confidence_band` ·
`alarm_level` · `verification_type` · `verification_status` ·
`verification_badge` · `dispatch_type` · `dispatch_status` ·
`request_status` · `notification_type` · `notification_status` ·
`neighborhood_response` · `overlap_decision` · `map_layer_type` ·
`map_layer_operation` · `hydrant_status` · `risk_level` ·
`equipment_status` · `device_platform`

`area_status` in v11: `reported`, `verified`, `en_route`, `arrived`,
`fire_out`, `post_incident_report`, `closed`, `rejected`, `merged`.

### 4.4 Notes

- Row-level security is enabled on every table. The API connects as
  `service_role` and enforces authority in application code (§2.6).
- `users.badge` and `areas.confidence_band` are **generated columns** — a
  client cannot set them.
- `public.org_roster` exists in the schema but **no application code reads
  or writes it**. Membership lives in `users.primary_org_id`.
- `evacuation_sites` no longer constrains geometry to the Pasay boundary.
- `dispatch_logs` is dead schema pending removal.

---

## 5. API SPECIFICATIONS

**~120 endpoints across 24 modules.** v11 removes two dispatch endpoints and
adds one Accept endpoint. Net: one fewer.

| Module | Endpoints | v11 changes |
|---|---|---|
| `auth` | 8 | — |
| `verification` | 9 | — |
| `reports` | 2 | — |
| `areas` | 6 | — |
| `incidents` | 16 | **−2** dispatch, **+1** Accept |
| `post_incident_reports` | 3 | — |
| `map_layers` | 10 | — |
| `map_layers_admin` | 15 | — |
| `map_layer_requests` | 5 | — |
| `affiliates` | 6 | — |
| `alarm_requests` | 5 | — |
| `equipment` | 5 | — |
| `notifications` | 5 | — |
| `devices` | 4 | — |
| `admin` | 4 | **−1** accept-and-route (Admin Accept moved to `incidents`) |
| `fire_codes` | 3 | — |
| `hydrant_ops` | 3 | — |
| `organizations` | 2 | — |
| `ai` | 2 | — |
| `health` | 3 | — |
| `audit` | 1 | — |
| `incident_reports` | 1 | — |
| `ws` | — | — |

### 5.1 Authorisation Tiers

| Dependency | Who |
|---|---|
| `CurrentUser` | Any signed-in account |
| `StaffUser` | `admin` or `sub_admin` |
| `AdminUser` | `admin` only |

Plus the Coordinator/Observer check inside the incident routes (§2.6). The
Accept route accepts all three staff tiers but scopes Observer visibility
to their own `selected_agencies`.

---

## 6. PERFORMANCE

| Metric | Target |
|---|---|
| Report submission → clustered | < 3 s |
| Neighborhood notification fan-out | < 5 s |
| Map layer load | < 2 s |
| Accept → responders En Route on all surfaces | < 2 s |
| Responder GPS broadcast interval | 5 s while `en_route` or `arrived` |
| Incident list refresh | 10–15 s poll |
| Citizen reporting friction | *reduce, target TBD after Zarate benchmarks the current flow* |

---

## 7. EVALUATION FRAMEWORK

Unchanged: ISO/IEC 25010 across six characteristics, and the Technology
Acceptance Model across Perceived Usefulness and Perceived Ease of Use,
administered by survey to Fire Volunteer personnel and resident participants
after the pilot.

---

## 8. DEPLOYMENT

### 8.1 Current State

**Nothing is deployed.** The backend runs locally; the mobile app reaches it
over the LAN.

- **Android blocks cleartext HTTP** from API 28. `network_security_config.xml`
  permits only the named development hosts. A deployed HTTPS backend needs
  no entry — and the exception list should be deleted when one exists.
- **Release builds sign with the debug key.** A keystore and
  `android/key.properties` are required before distribution. Both are
  gitignored; neither exists yet.
- **The Observer Console does not yet exist as a deployed target.** The
  codebase will be added under `observer-web/` next to `admin-web/`.

### 8.2 Repositories

| Repository | Branch | Contents |
|---|---|---|
| `M2STZ-Crew/replit-backend` | `main` | API, migrations, tests, `admin-web/`, `observer-web/` *(to be added)* |
| `M2STZ-Crew/replit-android` | `main` | Flutter app |

Both are **public**. Secrets are excluded by `.gitignore`.

---

## 9. COST

| Service | Tier | Limit that will bite first |
|---|---|---|
| Supabase | Free | 500 MB database; storage egress |
| Firebase FCM | Free | — |
| Mapbox | Free | 50,000 map loads / month |
| SMS provider | **In search** — see §10.3 | — |

---

## 10. RISK

### 10.1 Technical Risks

| Risk | Mitigation |
|---|---|
| GPS inaccuracy indoors | 300 m cluster radius absorbs it; accuracy is recorded per report |
| Photo GPS spoofing | EXIF cross-referenced against the device fix; a discrepancy flags for review |
| Duplicate reports | Clustering (§2.3) |
| False reports | Verification score + neighbourhood corroboration + audit trail + false-alarm flag on Post-Incident Report |
| A third-party basemap disappearing | CARTO broke in v9. Tiles now come from one module per platform, so a future swap is one edit |

### 10.2 Operational Risks

| Risk | Mitigation |
|---|---|
| An agency acting outside its remit | §2.6, enforced server-side |
| No agency accepts an Area | Admin retains an override Accept (§2.6.2) |
| Duplicate Accept race between agencies | Server serialises the transition; first Accept flips the Area, subsequent ones write acknowledgment rows only |
| Dispute over a decision | `audit_logs` retains the actor's role and agency at the time |
| Post-Incident Report never filed | The `closed` transition is blocked until submission; the incident stays visible in a "pending report" tray until the captain files |
| False alarm on scene | Team captain sets the false-alarm flag on the Post-Incident Report; `fire_out → closed` proceeds normally |

### 10.3 Known Gaps

Stated rather than hidden. Each is real and each has an owner.

| Gap | Effect | What it needs |
|---|---|---|
| **SMS provider not chosen** *(v11, superseding Twilio note)* | Phone verification is blocked, capping every Area's confidence below `high` | Choose a provider; verify a production sender |
| **Nothing is deployed** *(v9)* | Demonstrable only on the team's own network | Host the API with HTTPS |
| **Release builds sign with the debug key** *(v9)* | Cannot be distributed | Generate a keystore |
| **National ID review is manual** *(v9)* | Admin workload; slower awards | The automated KYC provider has no credits |
| **Database password exposed in an earlier session** *(v9)* | Credential known outside the team | **Rotate** |
| **The shared test password is compromised** *(v9)* | The same password is used by every `@testing.com` account against the live deployment | Rotate before real volunteer data exists. The value is deliberately not written down here: this repository is public |
| **`org_roster` unused** *(v9)* | Dead schema | Remove, or use it |
| **Observer Console not yet implemented** *(v10)* | Observer sub-admins currently have no surface | Scaffold `observer-web/` |
| **Post-Incident Report not yet implemented** *(v10)* | The lifecycle change is documented; the endpoint, table and mobile form do not exist | Add the migration, three endpoints, and the mobile form |
| **Notification sounds not yet selected** *(v10)* | Placeholder cues in §2.8 are text descriptions only | Select or record the four audio files |
| **Citizen reporting time not yet measured** *(v10)* | §6 target is "reduce"; bottleneck unknown | Zarate to benchmark the current flow end-to-end |
| **v11 lifecycle migration not yet written** *(v11)* | `area_status` still carries v10 values; dispatch endpoints still exist | Write the migration; delete the two dispatch routes; wire the Accept endpoint; remove the dispatch UI |
| **`dispatch_logs` is dead schema** *(v11)* | Table exists, nothing writes to it | Drop the table once no code path reads it |
| **Citizen app reads at B2, not A2** *(new)* | Written in a register harder than the emergency it reports | Rewrite the citizen surface to CEFR A2 (§2.10) |
| **No Tagalog** *(new)* | English-only excludes many of the residents the system is for | Translate the citizen surface; decide how the language is chosen and remembered (§2.10) |
| **Text logo has no light-ground variant** *(new)* | The wordmark is light-on-dark, and a light ground now exists | Draw the dark-on-light counterpart and bind it to the theme token (§2.7) |

---

## 11. SUCCESS METRICS

### 11.1 Technical

- Clustering correctly groups reports of one incident
- Every lifecycle transition is validated server-side, including
  `reported → verified → en_route` in one atomic Accept and
  `fire_out → post_incident_report → closed`
- Every consequential action, including subsequent-agency Accepts, appears
  in `audit_logs`
- An observer receives 403 on reject; Admin receives 403 on reject
- Only a Fire Volunteer or BFP Sub-Admin can reject
- The Accept endpoint is idempotent for the same actor on the same Area
- `flutter analyze` clean; **21** mobile widget tests; **86** backend test
  functions

### 11.2 Operational

- Time from report to first Accept
- Time from Accept to Arrived
- Time from Fire Out to Post-Incident Report filed
- Proportion of Areas reaching `high` confidence *(currently zero — §10.3)*
- False-alarm rate (from the Post-Incident Report flag)

### 11.3 Research

ISO/IEC 25010 and TAM instrument results (§7).

---

## 12. FUTURE

### 12.1 Recommended Next — in priority order

1. **Choose an SMS provider and integrate it.** Unblocks phone verification
   and the confidence formula.
2. **Write the v11 migration** — rename `area_status` values, add
   `false_alarm` to `post_incident_reports`, wire the Accept endpoint,
   delete the two dispatch endpoints.
3. **Scaffold the Observer Console** and wire the Accept action.
4. **Implement the Post-Incident Report** — endpoints, table columns,
   mobile captain form.
5. **Deploy the backend over HTTPS**, then delete the cleartext exception
   list.
6. **Rotate the exposed database password.**
7. **Generate a release keystore.**
8. **Select the notification sounds** with the client during pilot.
9. **Drop `dispatch_logs`** once no code path references it.
10. Offline report queuing — the design already promises it.
11. **Rewrite the citizen app at CEFR A2** (§2.10). Cheap, touches no logic,
    and it is the surface a stranger uses once, badly, in a hurry.
12. **Add Tagalog to the citizen surface** (§2.10). Larger than the rewrite and
    worth doing after it, so there is one clear set of strings to translate
    rather than two.
13. **Draw the light-ground text logo** (§2.7).

### 12.2 Long-Term Vision

Expansion to other Metro Manila cities; integration with national emergency
response; multi-hazard support; pattern-based prank detection.

---

## 13. MEETING RECORD — Meeting 12

**Date:** 7 September 2026, 3:00 PM
**Location:** NTC Room 401 or the faculty room
**Participants:** Sir Carlito L. Cunanan (adviser), M2STZ team
**Client:** Not involved

**Insights raised by Sir Carlito and reconciled by the team.**

- Police, Medical and Barangay need their own dashboards, viewing and
  tracking, with an Accept action on the map and no Reject. → §2.6, §2.5
- Admin dashboard needs a red count badge, notification sounds, and
  clickable incident cards. → §2.8, §2.9
- Evacuation site scope can extend beyond Pasay. → §2.4
- Post-response paperwork is time-consuming and should move to after
  fire-out. → §2.5.3 Post-Incident Report
- Distinct notification sounds per response-team category. → §2.8
- The citizen flow currently takes about 20 seconds and should be faster;
  the bottleneck is not yet identified. → §6

**Reconciled by the M2STZ leader.**

- The four-tier hierarchy — Admin, Sub-Admin (team captain), Response
  Team, Citizen (§2.6).
- Observer platform is web (§2.6, §3.1).

**Applied in v11 as a further simplification.**

- The two-step verify-then-dispatch was collapsed into a single Accept
  available to Admin, Coordinators and Observers (§2.5.1).
- Manual choice of truck and roster at dispatch time was moved to the
  Post-Incident Report (§2.5.3), so responders can leave the moment Accept
  fires. This came from the team's own review of the v10 lifecycle after
  Meeting 12, not from Sir Carlito directly.

---

## 14. CONCLUSION

v8 described a system that was designed. v9 described one that exists. v10
described one that had been reviewed. **v11 describes one that has been made
simpler.**

The three core innovations remain implemented and working: progressive
verification, 300 m crowdsourced corroboration, and area-based clustering
with versioning and merge. The four-tier role model, formalised in v10,
stands. What v11 changes is the operator's workflow: Accept is now one act,
not two. The paperwork is now after the fire, not during it. Admin does not
route by hand any more, because the reporter already said who they wanted.

What v11 also does, following v9's example, is write down what does not yet
work. The migration is not written. The Observer Console is not
implemented. The Post-Incident Report is not implemented. Notification
sounds are placeholders. Each of those is recorded in §10.3 with what it
needs, because a document that only lists what went well is not much use to
whoever picks this up next.

---

*Document maintained alongside the code at `MASTER_CONTEXT_v11.md` in
`M2STZ-Crew/replit-backend`. Section numbering follows v8 through v10 so that
code comments referencing "Section 2.6", "Section 7 #22" and similar remain
valid.*
