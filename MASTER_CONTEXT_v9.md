# RepLiT Master Context Document — v9.0

**Report Location and Incident In Time**
An Area-Based GPS Clustering and Progressive User Verification System for Fire
Volunteer Organizations in Pasay City

| | |
|---|---|
| **Document version** | 9.0 |
| **Last updated** | 7 September 2026 |
| **Development team** | M2STZ |
| **Adviser** | Mr. Carlito L. Cunanan, MIT |
| **Institution** | National Teachers College |
| **Supersedes** | v8.0 (17 May 2026) |

---

## VERSION HISTORY

| Version | Date | Changes |
|---|---|---|
| v7.0 | April 2026 | Removed triangulation, added GPS clustering, added AI vision analysis |
| v8.0 | 17 May 2026 | Removed AI vision analysis; added Progressive User Verification, Crowdsourced Neighborhood Notification (300 m), Area-Based GPS Clustering with versioning |
| **v9.0** | **7 Sep 2026** | **First version written against the built system rather than the plan.** Adds the Coordinator/Observer authority model, the design system, and the Area merge lifecycle. Corrects the verification arithmetic. Records what is built, what is not, and what is broken. |

### What changed from v8

**Added**

- **Coordinator vs Observer authority** (§2.6). v8 named four roles but treated
  every Sub-Admin alike. Police, medical and barangay Sub-Admins are now
  read-only observers, enforced server-side.
- **Area merge** as a terminal lifecycle state (§2.5), with `merged_into_id`
  and an overlap decision workflow.
- **A specified design system** (§2.7). v8 contained no UI specification at all.
- **Progressive-verification arithmetic corrected** (§2.1). v8 described
  "40% phone, 90% National ID, 100% email", which conflated the award weights
  with the badge thresholds. They are different things.

**Changed**

- Basemap provider from CARTO to Mapbox (§3.1). CARTO's key-less dark tiles
  now return an "API KEY REQUIRED" watermark rather than map data.
- The Admin Console is a separate React application, not server-rendered
  pages (§3.1).

**Not built, and honestly recorded as such** — §10.3.

---

## 1. SYSTEM OVERVIEW

### 1.1 Project Description

RepLiT is an emergency reporting and coordination platform for Fire Volunteer
organisations. A resident reports an incident from a phone; reports made close
together in space and time are clustered automatically into a single
**Area**; a Fire Volunteer coordinator verifies the Area and dispatches units;
responders advance the incident from their own phones; every consequential
action is written to an append-only record.

The system's three original claims still hold, and all three are implemented:

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
barangay personnel participating for situational awareness.

Default map centre: **14.5378° N, 121.0014° E**.

### 1.3 Problem Statement

The operational gaps RepLiT addresses, unchanged from v8:

1. Duplicate reports of the same fire arriving as separate incidents
2. No way to judge whether a report is credible before committing units
3. False alarms consuming trucks that another emergency needs
4. No shared live picture of what is happening across the city
5. Coordination between agencies happening by phone call and memory
6. No durable record of who decided what, or when

v9 adds a seventh, discovered during implementation:

7. **Agencies that should only observe were able to act.** Police, medical and
   barangay Sub-Admins could verify, reject, dispatch and resolve incidents
   belonging to the fire response. §2.6 closes this.

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

> **v8 correction.** v8 stated "40% phone, 90% National ID, 100% email". Those
> are not award weights; 90 and 100 are badge *thresholds*. The awards are
> 40/50/10 and always were in the schema. The document was wrong, not the code.

**National ID capture is camera-only by design.** Neither the ID nor the selfie
may be chosen from the gallery. Attaching a saved picture is how somebody
submits an ID that is not theirs — a screenshot of another person's card, or a
photo taken from social media. Requiring a live capture forces physical
possession of the document, and it is what makes the paired selfie mean
anything: both images are taken in the same session.

Verification level is **advisory, never gating**. It is shown to coordinators
when they review a report. It does not slow an incident down, and no report is
refused for a low score.

### 2.2 Crowdsourced Neighborhood Notification

When a report creates or joins an Area, every user whose last known location is
within **300 m** is notified and asked one question: do you see it too?

- **Report** — corroborates. The neighbour is taken into the SOS flow so their
  confirmation becomes a real report with its own photo and GPS, not just a tap.
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
> currently capped below the `high` band. This is a configuration problem, not
> a formula problem.

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
dispatch counts and agency scoping. The citizen map draws `GET /areas`, which
gives the incident, its status, confidence and report count, but not who has
been sent. A resident does not need to know which unit is coming; they need to
know something is happening and where it is safe to go.

Fire and police station markers are a **static reference list held in the app**
(`lib/models/facility.dart`). There is no station GIS table on the backend, and
the detail sheet says so rather than implying live data.

### 2.5 Incident Lifecycle

```
pending → verified → dispatched → en_route → arrived → resolved
             ↓
          rejected                              (terminal)
             
          merged                                (terminal)
```

`resolved`, `rejected` and `merged` are terminal and leave the live feed
(`TERMINAL_STATUSES` in `app/services/incident.py`). `rejected` and `merged`
additionally cannot be versioned.

Every transition is validated server-side by `assert_transition`. A client
cannot skip a stage by calling an endpoint out of order.

### 2.6 Role-Governed Access Control — Coordinator vs Observer

Access is the product of two enumerations:

- `user_role` — `admin`, `sub_admin`, `response_team`, `general_user`
- `agency_type` — `fire_volunteer`, `bfp`, `police`, `medical`, `barangay`

**This is the significant addition in v9.** A Sub-Admin's authority depends on
their agency:

| Class | Agencies | May |
|---|---|---|
| **Coordinator** | `fire_volunteer`, `bfp` | Verify, reject, resolve, dispatch, withdraw dispatches, press fire codes |
| **Observer** | `police`, `medical`, `barangay` | See incidents that requested their agency. Nothing else. |

Additionally, **only a Fire Volunteer Sub-Admin may verify** — enforced in both
the route and a database trigger.

**Where it is enforced.** `assert_coordinator()` in
`app/services/incident.py`. Eight actions return HTTP 403 to an observer, with
a message that explains the boundary rather than a bare refusal:

> *"Your agency takes part for situational awareness only, so it cannot reject
> incidents. Fire Volunteer or BFP coordinators handle this."*

The Admin Console mirrors the same predicates in `admin-web/src/auth.jsx`
(`isObserver`, `canCoordinate`, `canVerifyIncidents`) so an action the server
would refuse is never offered. **The UI mirror is a courtesy; the server is the
authority.**

Visibility is scoped separately from authority, by
`reports.selected_agencies` — an observer sees the incidents where a reporter
asked for their agency, and no others.

### 2.7 Design System — *new in v9*

Both front-ends implement Claude Design hand-offs: **General User App v2**
(mobile) and **Admin Console** (web).

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

Radii: 11 chip · 12 control · 14 card · 16 panel · 20 sheet.

Type: `w900` uppercase names a thing; `w300` is prose; a 10 px `w700` uppercase
"eyebrow" labels every section.

Tokens live in `lib/theme.dart` and `admin-web/src/index.css`. Repeated shapes
live in `lib/widgets/design.dart`.

#### 2.7.1 The rule the implementation follows

**Never build an interface the backend cannot honour.** Where the design showed
something with no data behind it, it was left out and the reason recorded in a
code comment. Examples:

| Design element | Why it is absent |
|---|---|
| Console "Acceptance %" | No such metric exists |
| Suspend / Revoke organisation | No endpoint mutates an organisation |
| Mobile "Skip the photo" | The server rejects a report without one |
| Voice-note recorder | No endpoint accepts audio |
| Sign-up OTP box | Sign-up is email + password; phone is a later step |
| "Avg arrival" statistic | `/reports/mine` carries no dispatch timestamps |
| Hash-chained audit digest | `audit_logs` has no hash column — claiming it would be a fabricated security property |

A control that cannot work is worse than no control, and in an emergency app it
is worse still.

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
| **Mobile** | Flutter (Dart SDK ^3.11.1) · flutter_map · geolocator · camera · image_picker · firebase_messaging |
| **Push** | Firebase Cloud Messaging |
| **Basemap** | **Mapbox `dark-v11` raster tiles**, OpenStreetMap fallback |
| **SMS** | Twilio |

**Why Mapbox replaced CARTO.** CARTO's `dark_all` basemap was free and
key-less when first integrated. It now answers a key-less request with an
"API KEY REQUIRED" watermark tile instead of map data. Seven of the mobile
app's eight maps and both console maps were rendering a grey placeholder before
this was found. All ten now draw from one module per platform
(`lib/widgets/map_tiles.dart`, `admin-web/src/map/tiles.js`).

Raster rather than vector: the console renders through Leaflet, and adding a
second map engine would buy nothing a user of a dashboard would notice.

### 3.2 System Architecture

```
┌──────────────────┐         ┌──────────────────┐
│  Mobile (Flutter)│         │ Admin Console    │
│  4 roles         │         │ (React + Vite)   │
└────────┬─────────┘         └────────┬─────────┘
         │        HTTPS / JWT         │
         └────────────┬───────────────┘
                      ▼
            ┌───────────────────┐
            │   FastAPI         │
            │   115 endpoints   │
            │   23 route modules│
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
   Firebase FCM                  Twilio SMS
```

### 3.3 Data Flow — End to End

1. **Capture** — resident holds SOS 3 s → GPS fix → chooses agencies →
   photographs the scene → `POST /reports/submit` (multipart)
2. **Cross-reference** — server compares the photo's EXIF GPS against the
   device fix; a discrepancy over 100 m flags the report for closer review but
   does **not** reject it
3. **Cluster** — §2.3 resolves the report to an Area and recomputes confidence
4. **Notify** — residents within 300 m are asked to corroborate
5. **Summarise** — a background job writes a text summary for dispatchers
6. **Verify** — a Fire Volunteer coordinator verifies or rejects
7. **Dispatch** — units assigned; responders advance en route → arrived
8. **Resolve** — coordinator closes; the Area leaves the live feed
9. **Audit** — every step appended to `audit_logs` with the actor's role and
   agency *as they were at the time*

---

## 4. DATABASE SCHEMA

**19 migrations · ~30 tables · 15 enumerated types.**

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
| `user_verifications` | One row per channel per user |
| `dispatch_logs` | Unit assignments and their state |
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

### 4.4 Notes

- Row-level security is enabled on every table. The API connects as
  `service_role` and enforces authority in application code (§2.6), because the
  authority rules depend on relationships RLS cannot express cleanly.
- `users.badge` and `areas.confidence_band` are **generated columns** — a
  client cannot set them.
- `public.org_roster` exists in the schema but **no application code reads or
  writes it**. Membership lives in `users.primary_org_id`.

---

## 5. API SPECIFICATIONS

**115 endpoints across 23 modules.**

| Module | Endpoints | Purpose |
|---|---|---|
| `auth` | 8 | Sign-in, profile, location, sign-out |
| `verification` | 9 | Phone, email, National ID |
| `reports` | 2 | Submit, my reports |
| `areas` | 6 | Citizen-readable incident list and detail |
| `incidents` | 16 | Staff lifecycle, dispatch, agency scoping |
| `map_layers` | 10 | Read GIS layers |
| `map_layers_admin` | 15 | Create / update / delete layers |
| `map_layer_requests` | 5 | Field change requests |
| `affiliates` | 6 | Organisation onboarding |
| `alarm_requests` | 5 | BFP alarm escalation |
| `equipment` | 5 | Unit roster |
| `notifications` | 5 | Inbox, Report / Ignore |
| `devices` | 4 | FCM token registration |
| `admin` | 4 | User approval, ID review |
| `fire_codes` | 3 | Code catalogue and events |
| `hydrant_ops` | 3 | Ground-truth hydrant status |
| `organizations` | 2 | Directory and personnel |
| `ai` | 2 | Text summarisation |
| `health` | 3 | Liveness |
| `audit` | 1 | Action record |
| `incident_reports` | 1 | Per-incident evidence |
| `ws` | — | Realtime channel |

### 5.1 Authorisation Tiers

| Dependency | Who |
|---|---|
| `CurrentUser` | Any signed-in account |
| `StaffUser` | `admin` or `sub_admin` |
| `AdminUser` | `admin` only |

Plus the Coordinator/Observer check inside the incident routes (§2.6).

---

## 6. PERFORMANCE

| Metric | Target |
|---|---|
| Report submission → clustered | < 3 s |
| Neighborhood notification fan-out | < 5 s |
| Map layer load | < 2 s |
| Responder GPS broadcast interval | 5 s while dispatched |
| Incident list refresh | 10–15 s poll |

---

## 7. EVALUATION FRAMEWORK

Unchanged from v8: ISO/IEC 25010 across six characteristics, and the
Technology Acceptance Model across Perceived Usefulness and Perceived Ease of
Use, administered by survey to Fire Volunteer personnel and resident
participants after the pilot.

---

## 8. DEPLOYMENT

### 8.1 Current State

**Nothing is deployed.** The backend runs locally; the mobile app reaches it
over the LAN.

Consequences that must be resolved before a pilot:

- **Android blocks cleartext HTTP** from API 28. A network security config
  (`android/app/src/main/res/xml/network_security_config.xml`) keeps the secure
  default and permits only the named development hosts. A deployed HTTPS
  backend needs no entry — and the exception list should be deleted when one
  exists.
- **Release builds sign with the debug key.** A keystore and
  `android/key.properties` are required before distribution. Both are
  gitignored; neither exists yet.

### 8.2 Repositories

| Repository | Branch | Contents |
|---|---|---|
| `M2STZ-Crew/replit-backend` | `main` | API, migrations, tests, `admin-web/` |
| `M2STZ-Crew/replit-android` | `main` | Flutter app |

Both are **public**. Secrets are excluded by `.gitignore`: `.env`,
`env.json`, `google-services.json`, keystores, `key.properties`.

---

## 9. COST

| Service | Tier | Limit that will bite first |
|---|---|---|
| Supabase | Free | 500 MB database; storage egress |
| Firebase FCM | Free | — |
| Mapbox | Free | **50,000 map loads / month** |
| Twilio | **Trial** | **No verified caller IDs — see §10.3** |

---

## 10. RISK

### 10.1 Technical Risks

| Risk | Mitigation |
|---|---|
| GPS inaccuracy indoors | 300 m cluster radius absorbs it; accuracy is recorded per report |
| Photo GPS spoofing | EXIF cross-referenced against the device fix; a discrepancy flags for review |
| Duplicate reports | Clustering (§2.3) |
| False reports | Verification score + neighbourhood corroboration + audit trail |
| A third-party basemap disappearing | **Realised.** CARTO broke. Tiles now come from one module per platform, so a future swap is one edit |

### 10.2 Operational Risks

| Risk | Mitigation |
|---|---|
| An agency acting outside its remit | §2.6, enforced server-side |
| Coordinator unavailable | Any Fire Volunteer Sub-Admin may verify |
| Dispute over a decision | `audit_logs` retains the actor's role and agency at the time |

### 10.3 Known Gaps — *new in v9*

Stated rather than hidden. Each is real and each has an owner.

| Gap | Effect | What it needs |
|---|---|---|
| **Twilio is a trial account with no verified caller ID** | Phone verification has **never once succeeded**. Nobody can earn the +40%, which caps every Area's confidence below `high` (§2.3) | Verify a caller ID — free, about two minutes — or upgrade the account |
| **Nothing is deployed** | Demonstrable only on the team's own network | Host the API with HTTPS |
| **Release builds sign with the debug key** | Cannot be distributed | Generate a keystore; keep it and its passwords off the repository |
| **National ID review is manual** | Admin workload; slower awards | The automated KYC provider has no credits |
| **Database password exposed in an earlier session** | Credential known outside the team | **Rotate** |
| **Test password `Testing123!` is compromised** | — | Rotate before real volunteer data exists |
| **`org_roster` unused** | Dead schema | Remove, or use it |

---

## 11. SUCCESS METRICS

### 11.1 Technical

- Clustering correctly groups reports of one incident
- Every lifecycle transition is validated server-side
- Every consequential action appears in `audit_logs`
- An observer receives 403 on all eight coordinator actions
- `flutter analyze` clean; **21** mobile widget tests; **86** backend test
  functions

### 11.2 Operational

- Time from report to verification
- Time from verification to units on scene
- Proportion of Areas reaching `high` confidence *(currently zero — §10.3)*
- False-alarm rate

### 11.3 Research

ISO/IEC 25010 and TAM instrument results (§7).

---

## 12. FUTURE

### 12.1 What v8 listed for v9, and what happened

| v8 wishlist item | Status |
|---|---|
| Offline mode with report queuing | **Not built.** The design shows an offline screen; there is no queue behind it |
| SMS fallback for neighborhood notifications | Not built |
| Multi-language (Cebuano, Ilocano, Hiligaynon) | Not built — no localisation layer exists |
| External integration (national 911, BFP databases) | Not built |
| Smartwatch applications | Not built |
| Advanced analytics dashboard | Partial — the Situation Board and Audit Log are built |
| Predictive fire risk modelling | Not built |

### 12.2 Recommended Next — in priority order

1. **Verify a Twilio caller ID.** Free, minutes of work, and it unblocks the
   entire verification tier and the confidence formula. Nothing else on this
   list returns as much.
2. **Deploy the backend over HTTPS**, then delete the cleartext exception list.
3. **Rotate the exposed database password.**
4. **Generate a release keystore.**
5. Offline report queuing — the design already promises it.

### 12.3 Long-Term Vision

Expansion to other Metro Manila cities; integration with national emergency
response; multi-hazard support; pattern-based prank detection.

---

## 13. CONCLUSION

v8 described a system that was designed. **v9 describes one that exists.**

The three core innovations are implemented and working: progressive
verification, 300 m crowdsourced corroboration, and area-based clustering with
versioning and merge. The four-tier role model is enforced, and v9 adds the
distinction it was missing — that participating in a response and directing one
are different things.

What v9 also does, and what a specification usually will not, is write down
what does not work. Phone verification has never succeeded. Nothing is
deployed. Release builds cannot be distributed. Those are recorded in §10.3
with what each one needs, because a document that only lists what went well is
not much use to whoever picks this up next.

---

*Document maintained alongside the code at `MASTER_CONTEXT_v9.md` in
`M2STZ-Crew/replit-backend`. Section numbering follows v8 so that code comments
referencing "Section 2.6", "Section 7 #22" and similar remain valid.*
