# Changelog

Versions follow `MAJOR.MINOR.PATCH`. MINOR tracks the Master Context generation
(1.12.x implements `MASTER_CONTEXT_v12.md`); the backend, both web consoles and
the mobile app (`replit-android`) carry the same number.

---

## v1.12.33 — 13 November 2026 — Every sound anew; the National ID's own sounds; Barangay 76's teams

Backend only; app v1.12.42 goes with it. **No migration.** Deploy in either
order: a phone is told on the new channels only once it registers with app
v1.12.42, and on the channels it has until then.

### Changes

**Sounds** ("check all of the sounds and apply it to the new. because we found
some errors in sound"; the recordings in NOTIFICATION SOUNDS, by who hears them)
- **Every sound on a channel made anew** (`SOUND_CHANNELS_V2`). A phone that
  had the app before v1.12.23 still holds `alert_fire`, `alert_police`,
  `alert_medical` and `alert_barangay` by resource number, and the recordings
  added since moved the numbers: on such a phone a Medical alert played "fire
  out" and a Police alert the Medical sound. App v1.12.42 deletes every sound
  channel it had and makes new ones that name their file. A phone is told on
  them once it has registered with v1.12.42 (`device_tokens.app_version`;
  every push now passes each phone's version, `send_to_tokens(versions=)`).
  Until then it is told on the channels it has.
- **The National ID's own sounds** ("custom national id verified sound (id
  verified and rejected)"): approved plays ID VERIFIED, asked to try again ID
  NOT VERIFIED (`id_verified_v1`, `id_rejected_v1`). The inbox row names the
  sound too, for the iPhone, which hears its inbox. An app before v1.12.42
  has neither channel and hears these as before, with the phone's tone.
- **No phone tone** ("No phone tone anywhere"). These pushes had none of
  their own and played the phone's tone; now each plays its reader's own
  sound:
  - a responder's dispatch: their agency's recording;
  - an incident routed to a team's captains: their agency's recording;
  - BFP's answer to an alarm request: the fire recording;
  - the test alert: staff hear their agency's recording, everyone else the
    citizen one.

  On app v1.12.42, a push that names no sound at all plays the citizen
  recording.
- **A fire near a resident plays NEARBY INCIDENT** ("Nearby fire: NEARBY
  INCIDENT"). The first alert played the staff fire alarm; now it plays the
  citizen recording ("01 NEARBY INCIDENT"), as its reminders already did.
- The verified step's new recording ("02 REPORT ACKNOWLEDGED") ships in app
  v1.12.42, on its new channel.

**Barangay 76's fire and medic teams** ("barangay 76 is the central hub. they
were going to be notified about (fire, medic, and barangay)")
- Done in the data on 13 Nov, not in code. Six new accounts in Barangay 76
  itself, alerted by their own agency:
  - `barangay76fire.coordinator1`, `.coordinator2` and `.responder1`: Fire
    Volunteer.
  - `barangay76medic.coordinator1`, `.coordinator2` and `.responder1`:
    Medical.
- `barangay76.responder` is now `barangay76.responder1`.
- A fire now alerts Barangay 76's fire team along with Hercules and BFP. A
  medical report alerts its medic team: until now no account had the Medical
  agency, so medical reports alerted nobody.
- The responder tracker shows a responder's own agency before its
  organisation's, so Barangay 76's fire responder shows as fire, not barangay.

### Tests
- `tests/test_v1_12_33.py`:
  - Every sound has a new channel, none of them an old id.
  - Which app versions have the new channels.
  - Each sound's channel and file on a new phone, and an older app's.
  - One push splits by app version.
  - A push without versions goes as to older apps.
  - No phone tone on a new phone; silent reminders and "New Update!" are
    unchanged.
  - Every push in the service passes its phones' versions (a scan of the
    code).
  - The National ID result's two sounds.
  - A dispatched responder's agency sound.
  - The test alert's sound, by role.
  - The tracker's agency.
- Updated, because the behaviour changed: `tests/test_push_alerts.py` and
  `tests/test_citizen_language.py` (a neighbour's first alert),
  `tests/test_staff_language.py` (a routed captain's sound) and
  `tests/test_alarm_escalation.py` (BFP's answer).

---

## v1.12.32 — 13 November 2026 — "New Update!" as soon as a release is out

Backend only; app v1.12.41's release workflow asks for it. **No migration.**
Deploy this first: until it is live, the workflow's ask finds no endpoint
and gives up with a warning, and the release still goes out.

### Changes

**Logic**
- **"New Update!" goes within seconds of a release** ("the "new update"
  push notification doesn't work on my android phone"). It was sent, but
  only at the service's next check, 10 minutes apart: app 1.12.40 was
  published at 12:16:56, the phone had installed it from the update banner
  by 12:18, and the 12:26 check found it up to date, so it was never told
  (another phone, still on 1.12.39, was told at 12:26). Now:
  - `POST /app-updates/check` (new, public): the app's release workflow
    asks for a check as soon as it has published. It takes nothing from the
    caller: the release is read from GitHub, as the scheduled check reads
    it, and each person is told once per version. It answers with the
    version it found (`{"version": "1.12.41"}`), not how many were told.
    Asks within 10 seconds of the last ask get that check's answer, without
    reading GitHub again.
  - The scheduled check runs every **2 minutes** (`APP_UPDATE_CHECK_MINUTES`,
    10 before), for when the ask does not arrive.
  - Checks run one at a time, so the scheduled one and an ask cannot both
    tell the same person.
  - Nobody told of a version is told of an older one afterwards (a check
    that reads the release a moment late): versions compare as numbers.
  - Each send is logged (`app_update_sent`: channel, sent, failed), so "it
    did not arrive" has an answer in the logs.

### Tests
- `tests/test_v1_12_32.py`: the ask, with no account, tells the phones behind
  at once, with the recording, and answers with the version alone; it takes
  no version from the caller; a release that cannot be read answers null;
  two checks at once tell each person once (fails without the lock); a burst
  of asks reads GitHub once, and again after 10 seconds; a failed
  announcement does not stop the checks; the query passes over anyone told
  of the version or a newer one; the 2-minute default.
- `tests/test_v1_12_29.py`: the query's "not told yet" is now "not told of
  this version or a newer one".
- Checked on production's own rows (read only): for 1.12.41 the query names
  all three Android phones, each with the recording; for 1.12.39 it passes
  over the phone already told of 1.12.40.

---

## v1.12.31 — 13 November 2026 — Map settings draws its layers' icons

Admin console only; the service is as in v1.12.30. **No migration.**

### Changes

**Admin console**
- **Map settings: icons in place of emoji** ("change those emoji to icons
  that is in map settings and use ICON FOR ADMIN MAP for those new
  icons"). Risk Areas, Evacuation Sites, Fire Hydrants, Bodies of Water
  and Underground Cisterns show the supplied icons
  (`admin-web/public/icons/layers`, unedited), in each layer's colour, on
  its tile and over its list, drawn the way the rest of the console draws
  its icons (`<Icon>`).

---

## v1.12.30 — 12 November 2026 — "New Update!" in its own voice

Backend only; app v1.12.38 goes with it. **No migration.** Deploy in either
order: until a phone has app v1.12.38 it is told as before.

### Changes

**Logic**
- **"New Update!" plays its own recording, in the reader's language**
  ("update notification sound is in my downloads (replit tutorial). so put
  it"; answered: English accounts hear the English one, Tagalog accounts the
  Tagalog one, and it still vibrates). A phone with app v1.12.38 or later is
  told on its language's channel, `app_update_en_v1` or `app_update_tl_v1`,
  which the app makes with the recording (`update_en`, `update_tl`; Android
  before 8 plays the file the push names). A phone on an older app has
  neither, so it is told on `app_updates_v1` with its own tone, as in
  v1.12.29. One person with phones on both is told once, each phone as it
  can play it.

### Tests
- `tests/test_v1_12_30.py`: which phones have the recordings (and the older
  apps' version labels); each language's channel and recording; an older
  phone's tone; one person with two phones told once; Android's settings for
  a recording.

---

## v1.12.29 — 12 November 2026 — "New Update!", the first fire team, the version alone

Backend and the APK page; app v1.12.37 goes with it. **No migration.** Deploy
in either order: an app before v1.12.37 shows the update push on its default
channel, and reads the fire type as before.

### Changes

**Logic**
- **"New Update!"** ("create an "New Update!" notification, the sound to be
  follow. still vibrates"; answered: a push when a release comes out, the
  phone's own tone for now). Every 10 minutes the service reads the app's
  newest release (its `latest.json`, a download, not GitHub's rate-limited
  API) and tells everyone on an Android phone on an older version, once per
  version: a push on its own channel, `app_updates_v1` (the phone's tone and
  vibration), and a row in their inbox (`type = app_update`), which is what
  marks them told. A phone's version is the one it registered with; "1.12.36
  (58)" from an older app reads as 1.12.36. It runs only where the service
  has a public address (Render), never on a laptop or in the tests.
  `APP_UPDATE_CHECK_MINUTES` (default 10; 0 is off).
- **Only the first fire team says what is burning** ("the first fire
  organization will fill out so that the second or next fire organization
  arrived will not fill that out"). `POST /incidents/{id}/fire-type` takes a
  fire team's answer (Fire Volunteer or BFP), the first to answer; after
  that only that team corrects it. Police, medical and barangay get 403
  `fire_team_only`; a later fire team 409 `fire_type_answered`, naming the
  team that answered, checked under the Area's lock. The incident says which
  team answered (`fire_type_org_id`, `fire_type_org_name`).

**APK download page**
- **The version alone** ("remove the build number. it is just the version of
  app will be remain seen in any platforms"): "1.12.37", and the file named
  for the version; older releases' names are shown without their build
  number too.
- **"What's new:"** is the list it shows from the release notes ("for
  testers" wording is gone from the system); older releases' "New for
  testers:" lists still read.

### Tests
- `tests/test_v1_12_29.py`: the release manifest read, and what is told
  when it cannot be; who is behind (and the older apps' version labels);
  the push's channel, words in both languages, inbox first, dead tokens
  switched off; the fire-type rule for every agency and team; the APK page.

---

## v1.12.28 — 12 November 2026 — An affiliate's standing: suspend, revoke, delete

Backend and Admin console; no app change (app v1.12.36 words the refusal).
**Run the migration `20261112120000_affiliate_standing.sql` before this
deploys.** Until it runs, every organisation reads as active and the three
actions fail.

### Changes

**Logic**
- **Affiliate management** (12 November: "freeze account, or soft delete, or
  hard delete, for revoked reasons"; answered: all three, each with a reason,
  audited). For the reviewers of affiliates — the system Admin and the
  central hub:
  - **Suspend** (freeze): nobody of the organisation signs in or acts; Restore
    undoes it any time. `POST /affiliates/organizations/{id}/suspend`.
  - **Revoke** (soft delete): the same, and it leaves the network with its
    records kept; Restore undoes it for 30 days, after which it can apply
    again. `.../revoke`, `.../restore`.
  - **Delete permanently**: only an organisation with no incidents on record
    (nothing acknowledged, responded to, routed, filed or reported by it), its
    name typed to confirm; its accounts are deleted from Supabase Auth and the
    organisation with them. With incidents on record it is a 409
    `has_incidents`: revoke it instead. `.../delete`.
  - The reason is one of misconduct, inactive, duplicate, fraudulent
    application, the organisation's request, other (other needs a note);
    every change is in the audit log (`affiliate.suspend`, `.revoke`,
    `.restore`, `.delete`). The central hub and the reviewer's own
    organisation are refused (409), so nobody locks the reviewers out.
- **A frozen organisation's people are refused on every request**: 403
  `organization_suspended` or `organization_revoked`, saying to ask the
  central hub. Read through `to_jsonb`, so it is a no-op before the migration.
- `GET /organizations` carries `standing`, `standing_reason`, `standing_note`,
  `standing_changed_at` and, for a revoked one, `restorable_until`.

**The APK download site** (`apk-web/`, for reportwhatslit-apk.vercel.app;
Figma "Admin web experience · APK download")
- One page: the app, its version, release date and size, **Download latest
  APK**, what's new, how to install step by step (unknown apps, Play
  Protect), and where to ask for help. It reads the newest release from the
  app repository's GitHub releases each time it opens — the same release
  "Check for updates" installs — so a new version needs no edit. Dark and
  light from the design system, Inter, 375 px and up. A Vercel project whose
  root is `apk-web/` serves it; nothing to build.
- **The console's domain change**: it is served at
  **reportwhatslit.vercel.app**, and reportwhatslit-admin.vercel.app and the
  old replit-backend-5u9u.vercel.app redirect there (Vercel). The backend
  always allows all three (`CONSOLE_ORIGINS`, whatever `CORS_ORIGINS` says),
  so a later change needs no edit on Render; and the console's
  `/installation` goes to the download page.

**UI (Admin console)**
- Affiliates → Network: the status says Suspended or Revoked. The
  organisation's dialog has a **Standing** section with Suspend, Revoke,
  Restore and Delete permanently, each asking for the reason (and a note for
  Other, the name typed out to delete). Not offered for the central hub or
  the hub's own organisation.

### Tests
- `tests/test_affiliate_standing.py`: suspend freezes and is audited, Other
  needs a note, an unknown reason is refused, the hub and your own
  organisation are untouched, revoke then restore within 30 days, not after,
  revoked must be restored before a suspend, delete needs the name and no
  incidents, and removes every account; the frozen sign-in check; the
  migration's reasons.
- Failing before this release and unchanged by it: `tests/test_smoke.py` and
  `tests/test_national_id.py`'s photo removal, 7 in all.

---

## v1.12.27 — 12 November 2026 — 50 m / 100 m, adults only, what's burning

Backend and Admin console, with app v1.12.34. **Run the migration
`20261112090000_fire_type_on_arrival.sql` before this deploys** (with
v1.12.26's, if it has not run yet). Until it runs, incidents still list (the
fire type reads as empty) but setting one fails.

### Changes

**Logic**
- **50 m incident, 100 m corroboration** (12 November: "change the area to
  50m actual incident, 100m corroboration"). A report joins an Area when it is
  within 50 m of the Area's centre (it was 300 m); two separate Areas within
  100 m are flagged as maybe one fire (was 600 m); and the neighbours asked
  "Is there a fire near you?" are those within 100 m (was 150 m).
- **Adults only** ("date of birth: don't accept 17 y/o and below"). A date of
  birth under 18, at sign-up or on the profile, is a 400 `underage`
  ("You must be 18 or older to use RepLiT."), counted on the Philippine
  calendar; one in the future is a 400 `invalid_date_of_birth`. The date of
  birth stays optional. `app/services/age.py`.
- **Staff reports count fully** (PRD v14 §4.1, §4.6.3): a report from a
  Coordinator or Responder carries V = 1.0 in the Area's confidence, whatever
  their own profile shows. Coordinators and Responders report a fire with the
  same flow as residents (app v1.12.34).
- **What's burning, on arrival** (PRD v14 §4.5.3; Figma C18 / R08b).
  `POST /incidents/{id}/fire-type` with `fire_type` (structural, electrical,
  vehicular, rubbish, grass, chemical) and `fire_subtype` for the three that
  have them (structural: residential, commercial, industrial; no Agricultural,
  PRD v14). A Coordinator, or a Responder going to the incident, sets it on
  scene; a later answer corrects it, up to the Post-Incident Report. Before
  arrival it is a 409 `not_on_scene`. Audited as `incident.fire_type`;
  incidents carry `fire_type`, `fire_subtype`, `fire_type_set_at` and, in
  detail, `fire_type_set_by_name`.
- **Back to the app after confirming an email**: every page the emailed link
  lands on has an **Open RepLiT** button (`reportwhatslit://`, an `intent:`
  link on Android), where the waiting sheet sees the address confirmed.
- **The Post-Incident Report queue** (12 November: "only organizations that
  joined an incident can file a PIR"; "one organization's PIR clears it for
  other joined organizations"; "CIAR must not initialize until every joined
  organization has filed its PIR"). A team *joined* when it acknowledged the
  incident or someone of it went, and it is a fire team (Fire Volunteers or
  BFP, whose captains file). Now:
  - only a joined team files; another is a 403 `not_joined`;
  - the incident stays at **To file** until every joined team has filed, so
    one team's report no longer takes it out of the others' trays; the last
    report closes it;
  - the **CIAR is written only then**: `POST /ai/{id}/summary` before that is
    a 409 `pir_pending` naming who it waits for, and the AI summaries list
    shows such an incident as `waiting` (with `pir_waiting`) and starts
    nothing;
  - an incident no fire team joined is closed by the first report, as before,
    and one closed before this release still takes the reports of the teams
    that responded.
  Incident detail carries `pir_teams_expected`, `pir_teams_filed` and
  `pir_waiting_on` (names). `app/services/pir_queue.py`.
- **Every alert vibrates** ("vibration when notifying, both Android and iOS,
  every stage and every notif"). The agency alert channels always vibrated;
  the citizen ones and "updates" did not, and a channel's settings are fixed
  once a phone has made it. Pushes now name the vibrating copies app v1.12.35
  makes: `citizen_updates_v2`, `citizen_verified_v3`, `citizen_on_route_v2`,
  `citizen_on_scene_v2`, `citizen_fire_out_v2`, `citizen_rejected_v2` and
  `updates_v2`. An app before v1.12.35 shows them on its default channel, with
  the phone's tone.
- **One phone per account: the newest sign-in wins** ("single device only
  policy ... a warning and a button will lead to exit"). Each request's
  session (the token's `session_id`) must be the account's newest in
  `auth.sessions`; an older one is a 403 `signed_in_elsewhere`, which the app
  answers with its warning and Exit (v1.12.35). Read once per 15 s per
  account. If the database role may not read `auth.sessions` the check turns
  itself off and logs `one_device_check_unavailable`, rather than refuse
  everyone. `app/services/one_device.py`.

**UI (Admin console)** (one device)
- A `signed_in_elsewhere` answer signs the console out, and the sign-in page
  says the account was opened on another device.

**UI (Admin console)**
- The Area map draws the 50 m radius, a step closer in.

### Tests
- `tests/test_v1_12_27.py`: 18 and over (birthdays, 29 February, Manila's
  date), the radii, staff V = 1.0, the fire types and subtypes, the route, the
  Open RepLiT link per phone, the PIR queue and the CIAR's wait.
  `tests/test_email_link.py`: the button on the confirmed page (Android and
  iPhone) and on a dead link. `tests/test_pir_per_team.py`: one team's report
  leaves the incident to file for the others, the last closes it and starts
  the CIAR, a team that did not join is refused, and a late team still files
  on an incident closed before.
- Failing before this release and unchanged by it: `tests/test_smoke.py` and
  `tests/test_national_id.py`'s photo removal, 7 in all.

---

## v1.12.26 — 9 November 2026 — Barangay 76: every Admin function, all in one

Backend and Admin console; no app change. **Run the migration
`20261109090000_central_hub_all_in_one.sql` before this deploys**: until it
runs, the hub can press Decide on an alarm request and be refused by the
database, and it still signs in with its old address.

### Changes

**Logic**
- **The central hub does every Admin function, on every incident** (9
  November: "barangay 76 as a central hub with all admin functions in web, not
  separated admin, fire, medic, and barangay; it is all in one"). Its Admin has
  everything the system account has (acknowledge, overlaps, reject / fire out /
  dispatch, affiliates, National IDs, map layers, water, Coordinators, accounts
  of any role, every organisation, every record unredacted) and asks for and
  decides alarm levels too. It acts on Fire, Police, Medical and Barangay
  incidents alike; its acknowledgements are still recorded under Barangay, its
  own agency, and Barangay 76. Until now it was a Barangay Admin that also
  reviewed affiliates and IDs.
- **What the system account alone could do, the hub does too**
  (`AdminAccess.governs_all`): any organisation's equipment and Coordinators
  (it picks the organisation when it makes one; its own if it names none),
  every organisation's units on the live map, and withdrawing any alarm
  request.
- **The migration** lets the hub's Admin set any alarm level
  (`enforce_alarm_authority`, as BFP's), and moves its sign-in to
  **barangay76.admin@replit.com**. @replit.com has no mailbox, so the address
  it had stays as its personal email, confirmed, where Forgot password? sends
  the link. It changes nothing when the hub has no Admin or several, or when
  the address is taken, and says so in a notice. The password is unchanged.

**UI (Admin console)**
- The hub's top line reads "Central hub — every Admin function, on every
  incident, for every agency"; it makes Coordinators for any organisation, and
  the live map shows every unit, as for the system Admin. One check,
  `governsAll`, in `src/lib/access.js`.

### Tests
- `tests/test_admin_console_access.py`: the hub has the system's permissions
  and the alarm ones, acts on every agency's incidents, governs every
  organisation, and a turned-off hub still fails closed; the hub manages any
  organisation's equipment.
- Failing before this release and unchanged by it: `tests/test_smoke.py`
  (expects version 0.1.0) and `tests/test_national_id.py`'s photo removal, 7 in
  all.

---

## v1.12.25 — 9 November 2026 — The rejected sound, and verified's new channel

Backend only, with mobile v1.12.33, which has the recordings and channels; deploy
this first. No migration; nothing to set on Render.

### Changes

**Logic**
- **A rejected report plays its own recording** (9 November: "the sound of
  rejected is the default"): sound `rejected`, channel `citizen_rejected_v1`,
  where it played the general "Report updates" one.
- **Verified uses `citizen_verified_v2`.** The app's new `sound_rejected` file
  sorts before `sound_verified`, and a channel a phone made before app v1.12.23
  holds its file by number, so on such a phone the v1 channel would play the
  rejected recording. The v2 channel names its file.
- An app before v1.12.33 has neither new channel, so it plays the phone's own
  tone for verified and rejected until it updates.
- The En route fix is the app's (mobile v1.12.33): its recording had been a copy
  of the On scene one since 28 October.

### Tests
- `tests/test_lifecycle_sounds.py`: rejected's sound and channel, verified's v2,
  and one channel per stage.
- Failing before this release and unchanged by it: `tests/test_smoke.py`
  (expects version 0.1.0) and `tests/test_national_id.py`'s photo removal, 7 in
  all.

---

## v1.12.24 — 8 November 2026 — The server stays awake

Backend only; no app or console change. No migration. Nothing has to be set
on Render; one GitHub secret makes the safety net able to redeploy (below).

### Why
Render's free plan stops the service after 15 minutes without traffic from
outside and starts it again on the next request, which used to take about 50
seconds. On 7 November at 1:29 AM and 8 November at 1:24 PM it stopped
starting again: requests hung until they timed out, so neither the app ("RepLiT
did not answer in time") nor the Admin console ("The console couldn't reach the
server") could sign anyone in. There were no logs at all, a restart did not
start it, and only a manual deploy brought it back, twice. Waking it is
Render's job, out of our hands; not sleeping is not.

### Changes

**Logic**
- **The service keeps itself awake** (`app/workers/keep_awake.py`). Every
  `KEEP_AWAKE_MINUTES` (10, under Render's 15) it asks for its own `/health`
  through its public address (`KEEP_AWAKE_URL`, else `RENDER_EXTERNAL_URL`,
  which Render sets), which counts as traffic from outside; Render's own health
  checks do not. Off Render there is no such address and nothing runs. Staying
  up also keeps the 60 s neighbourhood alerts and the coordinator pings running
  through the night, which paused while it slept.
- **A safety net on GitHub** (`.github/workflows/keep-awake.yml`): every 10
  minutes it asks for `/health`, and if the service does not answer twice in a
  row it starts a deploy through Render's deploy hook, what fixed it by hand.
  **One-time setup:** Render > replit-backend-2li4 > Settings > Deploy Hook,
  copy the URL, and save it in this repository as the Actions secret
  `RENDER_DEPLOY_HOOK_URL`. Until then the workflow only reports.

**Cost**
- A month awake is 720 to 744 of the workspace's 750 free instance hours, with
  this the only active service (the other is suspended). A paid instance does
  not sleep at all; with one, set `KEEP_AWAKE_MINUTES=0`.

### Tests
- `tests/test_keep_awake.py`: the address is the service's own public
  `/health` and none off Render; the job knocks every 10 minutes, once at a
  time, and 0 turns it off; a failed knock is logged, never raised.
- Failing before this release and unchanged by it: `tests/test_smoke.py`
  (expects version 0.1.0) and `tests/test_national_id.py`'s photo removal, 7 in
  all.

---

## v1.12.23 — 7 November 2026 — Burner email addresses are refused

Backend and Admin console, with mobile v1.12.30, which says it in its own
words (older apps show the server's message). No migration; nothing has to be
set on Render, though two settings can now change the list there.

### Changes

**Logic**
- **Disposable Email Address (DEA) detection.** An address from a throwaway
  email service (mailinator.com, 10minutemail.com, yopmail.com and about ten
  thousand more) stops working within the hour, so it is refused wherever
  RepLiT takes an email it relies on: signing up, the email link, a staff
  member's personal email (Profile, a new Coordinator, a new responder), and
  an affiliate's contact email (the public form and the signed-in request).
  The answer is a 400 `disposable_email`, with `details.field` and
  `details.domain`, before anything is looked up, made or sent.
  (`app/services/disposable_email.py`)
- **The list** is the community-maintained disposable-email-domains blocklist,
  CC0 (public domain), 10,143 domains at upstream commit `a72c0ce` (4 November),
  bundled as `app/data/disposable_email_domains.txt`. A listed domain covers
  its subdomains (`x.mailinator.com`). The providers people really use (Gmail,
  Yahoo, Outlook, iCloud, Proton and the rest) are never refused, whatever the
  list says. `python scripts/update_disposable_domains.py` refreshes it, and
  refuses to write a list that looks cut off.
- **Two settings, no deploy:** `DISPOSABLE_EMAIL_DOMAINS_EXTRA` refuses more
  domains, `DISPOSABLE_EMAIL_DOMAINS_ALLOWED` lifts ones the list has wrong
  (comma-separated; changing them restarts the service).
- **Not checked:** signing in and resetting a password, so an account made
  with such an address before now keeps working (it just cannot confirm the
  email, for no trust from a throwaway inbox), and an Admin making an account
  by hand (POST /admin/users), which is how test accounts are made.

**UI (Admin console)**
- The Create Coordinator dialog and the public affiliation form say "Temporary
  email addresses can’t be used. Use an email that will last, such as Gmail or
  Yahoo.", in English or Tagalog. One place does it for every page
  (`src/api/client.js`), keyed on the error, not its wording.

### Tests
- `tests/test_disposable_email.py`: finding a burner however it is written and
  on a subdomain, the providers people use passing, the settings, the bundled
  list whole and credited, and every route refusing one before touching the
  database, Supabase Auth or Brevo.
- Failing before this release and unchanged by it: `tests/test_smoke.py`
  (expects version 0.1.0) and `tests/test_national_id.py`'s photo removal, 7 in
  all.

---

## v1.12.22 — 7 November 2026 — A resident's email link, sign-up's last step

Backend only, with mobile v1.12.29, which ends a resident's sign-up with this
link. No migration and nothing to set on Render. Deploy it before that app
reaches people; the app copes with v1.12.21 too, without the limits below.

### Changes

**Logic**
- **The email link is sign-up's last step** (7 November: "instead of OTP, they
  will confirm it via email in Gmail"). Mobile v1.12.29 asks for it the moment
  a resident's account exists. POST /verification/email/request now answers
  like the phone code's request, `{message, email, sent, expires_in_seconds,
  resend_after_seconds}`; a client that reads only `message` keeps working.
- **One link a minute, five a day**, per account
  (`EMAIL_LINK_RESEND_COOLDOWN_SECONDS`, `EMAIL_LINK_DAILY_LIMIT_PER_USER`):
  a 429 `email_link_cooldown` or `email_link_daily_limit`, with
  `details.retry_after_seconds`. Each link is a Brevo email, and the plan
  allows only so many a day. The email is sent inside the transaction, so a
  send Brevo refuses records nothing and spends neither.

**Fixed**
- **Asking again no longer un-confirms an email.** A confirmed address gets
  no email (`sent: false`) and stays confirmed; until now the request set it
  back to pending, and the 10% was gone until the new link was opened.
- **The link lands on a page in every case**, readable on a phone, in light
  and dark: confirmed, already confirmed (opening it twice changes nothing),
  expired, or replaced by a newer link, each saying what to do next. An
  expired or replaced link showed raw JSON, and the confirmed page was
  unstyled and tiny on a phone.

**Internal**
- The page a link lands on is one helper (`app/services/link_page.py`), for
  the staff links and this one.

### Tests
- `tests/test_email_link.py` (12, hermetic): sending, the wait and the day's
  cap, a refused send recording nothing, a confirmed address staying
  confirmed, and each page a link can land on.
- Failing before this release and unchanged by it: `tests/test_smoke.py`
  expects version 0.1.0, and `tests/test_national_id.py`'s photo removal
  (7 tests in all).

---

## v1.12.21 — 7 November 2026 — Staff sign-in addresses, change password, Tagalog for staff

Backend and Admin console, with mobile v1.12.28. **Two things before this
backend deploys:**

1. **Run the migration `20261106090000_staff_personal_email.sql`.** This
   backend reads `users.personal_email` on every signed-in request (GET
   /auth/me among them), so without it they all fail.
2. **Set `REQUIRE_CITIZEN_PHONE_VERIFICATION=false` on Render** before mobile
   v1.12.28 reaches people. That app signs up and signs in by email and asks
   for no mobile number while the SMS provider is undecided; with the gate on,
   a new resident would stop at "Verify your mobile number". Turning it back
   on needs no deploy.

### Changes

**Added**
- **Staff sign-in addresses, agency first** (the 6 November list). A new
  Coordinator or Responder signs in at an address made from the name, the
  agency and the role: Odyssey Bryan, a Fire Volunteer coordinator, is
  `obryan.fircor@replit.com`; a responder of theirs `jdelacruz.firres`. Every
  agency follows it (`fir`, `bfp`, `pol`, `med`, `bar`; `cor`, `res`),
  numbered after the surname when taken. Accounts made before keep their
  address.
- **A personal email for staff.** @replit.com has no mailboxes, so whoever
  makes the account gives the person's own email (`users.personal_email`).
  One link there, good for three days, confirms it and opens the set-password
  page through a fresh recovery link: no password passes through anyone.
  Forgot password? for such an account, by its sign-in or its personal email,
  sends the link there (one hour). Staff add or change theirs from Profile
  (`PUT /auth/me/personal-email`), confirmed by a link. The links carry a
  signed token (`app/services/staff_links.py`); one sent to an address the
  account no longer has does nothing.
- **Change password, `POST /auth/me/password`.** It checks the current password
  by signing in with it, sets the new one (8 to 128 characters), then signs out
  every other session; the one that asked stays signed in. A wrong current
  password is a 400 `wrong_password`, never a 401, which the app and the console
  read as an expired session. The same password again is `same_password`.
- **Staff alerts in English or Tagalog** (`app/services/staff_copy.py`): a new
  incident, the Coordinator's reminder, "You're dispatched", the routing alert,
  and an alarm request and its answer each follow the reader's `users.language`.
  The English is word for word what it was.
- **`GET /auth/me` returns `language`, `personal_email` and
  `personal_email_verified`,** so the app and the console start in the
  account's language and the Profile can show the personal email.
- **The Admin console in Tagalog.** English | Tagalog on the sign-in page and in
  Settings, saved to the account (`PUT /auth/me/language`); a choice made before
  signing in is saved once signed in. 1,034 lines, in everyday B1 Tagalog that
  keeps the words Admins already use (report, Area, dispatch, Coordinator) and
  BFP's own alarm terms. `npm run check:tagalog` fails when a line has no
  Tagalog or its `{blanks}` differ.
- **Change password in the console's Settings:** current, new and again.

**Changed**
- **Create Coordinator** (console) asks for the first and last name, shows the
  address the server will make as they are typed
  (`GET /admin/coordinators/email-preview`), and takes the Coordinator's own
  email instead of a sign-in email. A @replit.com address is refused there.
- **A coordinator's new Responder** (`POST /team/responders`) takes the
  responder's own email instead of a mobile number, and nothing comes back to
  hand over. An older app that sends no personal email still gets a temporary
  password, so making responders keeps working until it updates.

**Not changed**
- Accepting an affiliate application still makes its first Coordinator on the
  contact's own email, with no @replit.com address.

**Tests**
- `tests/test_change_password.py` (10), `tests/test_staff_language.py` (14),
  `tests/test_staff_email.py` (10), and the team, coordinator, email-template
  and password-reset tests for the new addresses and links.

### Verified

- Backend: pytest (786 passed; the two `test_smoke` version checks fail, as
  before), ruff; mypy reports only the existing `ai_summary.py:74`.
- Console: `vite build` and `npm run check:tagalog` (1,034 of 1,034); sign-in
  and Request access looked at in both languages.
- Not run: anything against the live server or database — the migration, a
  password change, a staff welcome email, a Tagalog staff alert on a phone.
  The Create Coordinator dialog was not seen in a browser: it needs an Admin
  session.

---

## v1.12.20 — 5 November 2026 — The 5 November issue list

Backend and Admin console, with mobile v1.12.24. **Two migrations — run them
before deploying this backend**, which reads both new columns:
`20261105090000_location_updated_at.sql` and `20261105090100_user_language.sql`.
One new optional setting, `NEIGHBORHOOD_LOCATION_MAX_AGE_MINUTES` (default 30).

### Changes

**Found**
- **The 150 m alert reached people who were not there.** The neighbourhood
  worker counted anyone whose last-known location was within 150 m, however old
  it was, and a phone reported it only when the app opened.
- **A report could leave the Fire Volunteers out.** `POST /reports/submit`
  took `selected_agencies` as given.
- **The light Admin console drew the dark map.**

**Changed**
- **150 m alerts count only a location reported in the last 30 minutes**
  (`users.location_updated_at`, stamped by `POST /auth/me/location` and by a
  report's own fix). The app keeps it fresh, open or closed.
- **Fire is always asked:** `fire_volunteer` comes first in every report's
  agencies, added when a request leaves it out.
- **Residents' alerts in English or Tagalog** (`users.language`,
  `PUT /auth/me/language`, `app/services/citizen_copy.py`): the neighbourhood
  alert, the six report updates, the National ID answer and the test alert.
  Staff alerts stay in English. Residents who have not chosen a language now get
  the neighbourhood alert in English, the app's default.
- **"The central hub", not "Barangay 76"**, in the 403s and the console copy.
- **Admin console:** Mapbox `light-v11` on the light ground; skeleton loaders
  wherever it said "Loading…".

**Tests**
- `tests/test_citizen_language.py`, `tests/test_phase6.py` (Fire always
  asked), `tests/test_fixes_oct24.py` (the 30-minute window).

---

## v1.12.19 — 2 November 2026 — Every RepLiT email on one formal layout

Backend, with mobile v1.12.23. No migration, no new setting, no new email. The
Admin console changes only its version number. Deploy order does not matter.

### Changes

**Found**
- **Five emails, five looks.** Verify your email, reset your password, the
  affiliate's "received" and "approved", and the new Coordinator's invitation
  were each a bare `<div>` with a heading, a paragraph and an orange button: no
  header, no footer, no word on why the email came.
- **The email-verification message had no plain-text part,** so a text-only
  client showed "Please view this email in an HTML-capable client."
- **Two emails put names in unescaped.** The verification email's greeting used
  the account's full name as HTML, and the affiliate approval used the
  organisation's name from the public form the same way.

**Changed**
- **One layout, `app/services/email_layout.py`, for all five.** A dark header with
  the app's mark (served by the Admin console, `assets/logo-mark.png`) and the
  coral wordmark; a white card with the heading, the message, one button with
  its link written out beneath it; a panel with how long the link lasts; a
  security note; a footer that says why the email was sent. The colours are the
  app's ground and coral and the reset page's light set; the button is coral ink
  `#A63A0A` under white text (6.5:1).
- **Built for mail clients.** Tables and inline styles; no web fonts, scripts or
  background images; a 600 px column that narrows on a phone; a hidden preheader
  for the inbox preview; dark colours where the client asks for them (Apple
  Mail, iOS Mail, Outlook for Mac). Gmail and Outlook, which recolour on their
  own, get a light card under a dark header.
- **Every email has a plain-text twin with the same words,** built from the same
  call, and every value a caller passes is escaped.
- **Formal wording, same meaning.** Each link's lifetime is now stated in the
  email itself, unchanged: 24 hours for email verification, one hour for the
  password links (reset, affiliate approval, Coordinator invitation).

**Unchanged:** recipients, subjects, links and their tokens, link lifetimes, the
cooldowns, the Brevo SMTP settings, when each email is sent.

**Tests**
- `tests/test_email_templates.py`: each email has the layout and a plain-text
  part, the link twice (button and written out), the stated lifetimes, no
  markup from a name or a link, and the verification route now sends text.
- `tests/test_lifecycle_sounds.py`: what a reporter hears at each stage (the
  mapping below), one push per status change, nothing at Reported, and the
  general "Report updates" sound for news that is not a stage.

| Stage | Event | Sound | Android channel |
|---|---|---|---|
| Reported | none | none | none |
| Verified | `incident_verified` | `sound_verified` | `citizen_verified_v1` |
| On the way | `incident_en_route` | `sound_on_route` | `citizen_on_route_v1` |
| On scene | `incident_arrived` | `sound_on_scene` | `citizen_on_scene_v1` |
| Fire out | `incident_resolved` | `sound_fire_out` | `citizen_fire_out_v1` |

**Not tested:** how the emails look in Gmail, Outlook or Apple Mail (they were
checked in a browser only, at 375 px and desktop, light and dark), and delivery:
no email was sent.

---

## v1.12.18 — 31 October 2026 — National ID, checked on PSA's PhilSys Check

Backend and Admin console, with mobile v1.12.21. No migration, no new setting.
Deploy the backend and console before handing out the APK: on the old server the
new app's QR photo is ignored. An older app is told to update and nothing is kept.

### Changes

**Found**
- **Nothing tested whether an ID was genuine.** A reviewer compared a photo with a
  selfie by eye. The Didit route was never connected to the app.
- **ID photos and selfies stayed in Storage for good.** Approving and rejecting
  never touched them, and nothing else deleted them.
- **The reviewer's reason never reached the resident.** `/verification/status`
  returned it and the app did not read it, so "What should they fix?" went nowhere.
- **Deleting a missing object counted as a failure.** Storage answers it with HTTP
  400 and the 404 in the body, not with a 404.
- **The app's upload skipped the shared client,** so an expired session failed it
  instead of renewing.

**Added or changed**
- **A QR photo and the holder's consent are required.** The app takes a third
  camera photo and a consent line that says what PSA records. The server refuses
  a submission without them before anything is stored.
- **PhilSys Check in the console.** Each review shows the QR photo, a download, a
  link to the site and its steps. The reviewer records what it said, in PSA's words.
- **Approving needs PhilSys Check's "Verified",** on the server. A failed check
  fills in the reason, with PSA's advice, and is recorded, as PSA's handbook asks.
- **Deciding deletes the photos, first.** If they cannot be deleted the decision
  stops, so a decided review never holds them. Object names lost their extension,
  so a second submission replaces the first instead of sitting beside it. An
  upload that fails partway removes what it stored.
- **The resident is told.** The decision reaches their inbox and phone, tapping it
  opens Verify your account, and the reason shows on the National ID row.

### Verified

- Backend: pytest, ruff; mypy reports only the existing `ai_summary.py:74`.
- The upsert, approve and reject SQL ran from the route files on a real Postgres
  16.2, through submit, reject, resubmit, approve and reject without a result. All
  11 statements prepare on the live schema, read-only.
- On real Storage, read-only: `&download=` returns an attachment, and deleting an
  object that does not exist now passes (it raised before).
- Console: the fictional preview at 1280, 1000 and 375 px, with no sideways scroll.
  Approve stays off until "Verified" is chosen, and both requests send the right
  body. Mobile: `flutter analyze` and `flutter test`.
- PhilSys Check's steps were followed on the live site as far as Select Image, so
  the console's wording is what the site shows today.
- Not run: a real PhilID or ePhilID through PhilSys Check, a submission against
  the live server, or anything on a phone. A photographed QR code may need retakes.

---

## v1.12.17 — 31 October 2026 — The console survives an adblocker

Admin console only, and only a rename; the version moves with it. Mobile stays
v1.12.20. No migration.

### Changes

**Found**
- **An adblocker blanked the console.** Filter lists hide elements by class name on
  every site, and the console named its classes `ad-`, for Admin. 15 of those names
  were on EasyList, among them `.ad-main` and `.ad-sidebar`. With both hidden only
  the dark page background was left, with the app still running underneath and
  nothing logged. `.ad-sidebar` alone left the sidebar missing.

**Added or changed**
- **The prefix is `rpl-`**: 337 class names, ids and the one CSS variable, 1,532 uses
  in 47 files. Nothing else changed. A test fails if an `ad-` name comes back.

### Verified

- Undoing the rename on all 47 files gives back the previous commit exactly, and the
  built CSS and HTML match it too.
- Every generic hiding rule from EasyList, Fanboy, AdGuard and uBlock Origin (40,504)
  ran as a selector on the live DOM of 13 console pages: no hits. The old names gave
  8 on the Dashboard alone. Sign-in and Register: no hits from 14,126.
- None of about 559,000 network rules from six lists matches the console's 85 built
  files or its 49 API paths.
- Backend: pytest, ruff; mypy reports only the existing `ai_summary.py:74`.
- Not run with a real adblocker extension: the rules were applied by hand.

---

## v1.12.16 — 31 October 2026 — Map editing, where it can be found

Backend and Admin console. Mobile stays v1.12.20. No migration.

### Changes

**Found**
- **The editor had left the page it used to be.** Until the pass 6 redesign
  (23 October) the sidebar's Live map was the editor, for every Admin. Since then
  Live map only shows the map, and the editor sat behind an unlabelled gear drawn
  only for `map.manage`, which v1.12.15 gave to the central hub alone. A Fire
  Volunteer Admin had no way to add, change or delete a risk zone or a hydrant.
  The server was not the problem: every map write type-checks against the live
  schema, and CORS allows PATCH and DELETE from the console.
- **The tests could write to the live database.** `with TestClient(app)` runs the
  app's startup, which opens the pool from `.env`, and the audit middleware writes
  through that pool, past every dependency override. A test added in v1.12.15
  left 8 rows in the live `audit_logs` (`map_layer.*`, user agent `testclient`, no
  actor). They are still there: the table is append-only.

**Added or changed**
- **`map.manage` for Fire Volunteer and BFP Admins**, beside the central hub. It
  covers adding, changing and deleting every map layer, the BFP hydrant import and
  reviewing map layer requests. Police, Medical and other Barangay Admins keep what
  they had: they see the map and may delete a water resource.
- **Map settings in the sidebar**, under Resources, for whoever may use it. It has
  its own address, so a reload stays there. The gear on the Live map leads to it,
  and Water resources has Add or change resources, which opens it on the hydrants.
  Water resources tells everyone else who adds and changes them.
- **The tests have no database.** `tests/conftest.py` empties `DATABASE_URL` before
  the app loads, and a test pins it. The suite went from 146 s to 63 s.

### Verified

- Backend: pytest, ruff; mypy reports only the existing `ai_summary.py:74`. The
  live count of `testclient` audit rows was 8 before the full run and 8 after.
- Every map write the routes make was prepared against the live schema, which
  type-checks the SQL and runs nothing. No map data was written.
- Admin: `vite build`, and on the console preview (fictional data), as a Fire
  Volunteer Admin: changed a risk zone's radius, had 6000 m refused, added and
  deleted a risk zone, added, changed and deleted a hydrant, reloaded on the page,
  and opened it on a phone width. It opens for BFP and the hub. Police gets no
  page, no gear and no button.
- Not run through the deployed console: that needs this version on Render and
  Vercel, and a signed-in Admin.

---

## v1.12.15 — 31 October 2026 — The 30 October issue report

Mobile is v1.12.20. Issues are numbered as in the report.

### Run before or after the deploy: `npx supabase db push`

- `20261031090000_positive_alarm_on_verify.sql`: until it runs, a verified Area
  gets no level, as before.
- `20261031090100_neighborhood_safe_answer.sql`: until it runs, "I am safe" fails
  and the app says the answer was not recorded. Report and Ignore keep working.

Neither depends on the backend, or the backend on it.

### Changes

**Found**
- **Nobody could reach Map Settings (03).** `map.manage` belonged only to the
  system Admin, and the 28 October account directory has none: the live database
  had no Admin holding it.
- **Sign-in delays are the server waking (06).** Measured against production:
  the first request after a quiet spell took 32.4 s, the next ones 0.08 s, and a
  login round trip 0.2 to 0.7 s. `render.yaml` is on the free plan, which sleeps.
  The app had no timeout and a spinner that never said why.
- **Fire staff were alerted by the resident's 150 m alert (04 A).** On the two
  live Areas that never asked for Fire, `incident_new` reached only the agencies
  asked; Fire coordinators got `fire_alert` because their phones were nearby.
  **Not changed: it waits on the decision below.**
- **"I am safe" had a screen and nothing behind it (09).** The card existed for
  the design only; no endpoint or enum value took the answer.
- **A test alert was two banners in a queue (07).** The API's toast (4 s) and the
  push's banner (10 s) ran one after the other, in either order.

**Added or changed**
- **Positive Fire Alarm is set by the first verify (11).** `enforce_alarm_authority`
  records it on `reported -> verified`, whoever verified, with the verifier as
  `alarm_level_set_by`. Unverified reports are never classified. Asking for it is
  refused in words, so an older app is told why; requests start at 1st Alarm and
  BFP's approval is unchanged. `alarm_level_set_at` now moves with each level (it
  kept the first time). Areas verified before this keep their record.
- **"I am safe" (09).** `POST /notifications/respond` takes `safe`, for a resident
  the alert reached, while the Area is live: 403 otherwise, 409 once it has ended.
  It stands once given: a repeat, or a later Report or Ignore, changes nothing.
  `GET /notifications/respond/{area_id}` says what they answered and whether they
  may. "I need help" stays out: it promises the responding Captain sees where
  they are, and nothing delivers that yet.
- **Map Settings (03).** `map.manage` goes to the central hub. The editor covers all
  five layers (A35 was blocked pending this decision), with loading, failed-load
  and validation states and the console's confirmation on delete.
  `include_inactive` lets only the editor see what it switched off, and map writes
  are audited (`map_layer.create`, `.update`, `.delete`).
- **Directions for every coordinator (04 B).** Police, Medical and Barangay
  coordinators get Route to the fire on an acknowledged Area. It records nothing:
  responding stays as it was, by the earlier decision that they acknowledge only.
- **Test alert (07).** A second one replaces the first in the shade, and reaching no
  phone is a 502 rather than "Sent to 0 device(s)". On the phone the result goes on
  the row, and the banner lasts 4 s.
- **Sign-in (06).** The app starts waking the server as the sign-in screen opens,
  says why after 6 s, and stops at 75 s with words instead of a spinner.
- **Hotlines (05).** The list was already on the phone; there was no way to it
  signed out. Emergency hotlines is now on the sign-in screen and on the screen
  shown when an account will not load, with no tabs leading anywhere else.
- **Wording.** "Organization" in the console and the server's messages (01),
  "Center" in the app (08), and 150 m where the app named the neighbourhood alert
  as 300 m (02). Comments, identifiers and API fields are unchanged.
- **Location plate (10).** One widget for every role: the app's ink on coral, about
  6:1. White on coral, which the resident's map drew, is about 2:1.

### Decisions needed

- **Mandatory Fire selection (04 A).** Not implemented. Until then a report that
  unticks Fire reaches no fire unit by design, and staff near it still get the
  resident alert. If it is approved, exclude staff from that alert at the same time.
- **Clustering radius (02).** `_CLUSTER_RADIUS_M` is 300 m, PRD v14 says 100 m, the
  issue says 150 m. It is drawn and worded as 300 m because that is what it does.
  Changing it changes which reports merge, so it is left for the team.
- **Keeping the server awake (06).** The cold start itself remains. A paid plan
  ends it; a keep-warm ping uses free instance hours shared across the workspace.

### Verified

- Backend: pytest, ruff; mypy reports only the existing `ai_summary.py:74`.
- The trigger and the safety upsert ran on a real local Postgres against these
  migration files (22 checks), since the fakes cannot execute them. Not on the
  live database.
- Mobile: `flutter analyze`, `flutter test`. Admin: `vite build`, and Map Settings
  driven in the browser on the console preview.
- Not tested on a phone: push in the background or locked, offline dialing, and
  sign-in timing across devices and networks.

---

## v1.12.6 — 7 October 2026 — Notifications outside the app, a fire alarm, and taps that open

### Changes

**Found**
- **No push had left the live server.** `/health/ready` on Render reported
  `"push": "failed"`: Firebase would not start there, so not one notification
  went out. The app and its registered phones were fine; the server could not
  send. Most likely cause: `FCM_CREDENTIALS_FILE` copied from a laptop `.env`,
  naming a key file that is gitignored and was never deployed. Render needs
  `FCM_CREDENTIALS_JSON` set to the key file's contents. That is a dashboard
  change, not code; see Regression Check.
- **Staff were never told about a new fire.** Under v10 a responder learnt of
  an incident from the dispatch push. v11 removed dispatch, and with it the
  only push staff got. `notify_responder_dispatched` and
  `notify_route_recipients` have had no caller since.

**Added**
- **A new fire alerts the staff who can see it**: every active responder and
  coordinator of each agency it was asked of. The two fire agencies see each
  other's fires, as in incident visibility. It goes out once, when the first
  report makes the incident; a report joining a known fire does not repeat it.
  Push type `incident_new`, plus an Alerts row of the same type for phones
  without a token (and the Observer Console's bell).
- **The fire alarm.** A push that says there is a fire (a new incident for
  staff, a neighbour's *first* alert, an alarm escalation) goes to the app's
  `fire_alerts` channel, which rings the app's fire alarm. Everything else goes
  to `updates` with the phone's own tone. The 300 m reminders after a
  neighbour's first alert (one a minute, up to ten) use the normal tone and
  replace one another in the shade; ten sirens would teach people to mute the
  app.
- **The server says why push will not start.** `/health/ready` adds
  `push_detail` when push failed: which variable to set and how. It never
  includes any of the credentials. The test push (`POST /devices/test`) says the
  same.

**Modified**
- `FCM_CREDENTIALS_JSON` forgives the usual paste mistakes: quotes around the
  value (as on a `.env` line) and doubled backslashes in the private key.
- Every push carries a `tag`, so news about the same incident replaces the
  last notification instead of stacking: `incident-`, `nearby-`, `report-`,
  `alarm-` + the incident id.

### Files Changed
- New: `tests/test_push_alerts.py`.
- `app/integrations/fcm.py` (channels, `android_config`, `fcm_failure_reason`,
  tolerant credentials), `app/services/incident_notify.py`
  (`notify_staff_new_incident`, `staff_agencies_for`; alarm requests ring;
  tags), `app/workers/neighborhood.py` (first alert rings, reminders do not),
  `app/api/routes/reports.py` (staff alert on a new incident),
  `app/api/routes/health.py` (`push_detail`), `app/api/routes/devices.py`.
- `tests/test_map_feed.py`, `tests/test_report_in_progress.py`: their stand-in
  database gives `report_count`.
- `pyproject.toml`, `uv.lock`, `app/core/config.py`, `admin-web/package.json`,
  `observer-web/package.json`: version 1.12.6.

### Database Changes
None. `incident_new` is a new value in `notifications.type`, which is text.

### API Changes
| Endpoint | Change |
|---|---|
| `POST /reports/submit` | When the report makes a new incident, staff who can see it get an `incident_new` push (fire alarm) and Alerts row. Best-effort: a failure never fails the report. |
| `GET /health/ready` | `checks.push_detail` when `push` is `failed`. |
| `POST /devices/test` | A failed start's 503 names what to fix. |
| FCM payloads | `android.notification.channel_id` `fire_alerts` (`sound: fire_alarm`, priority max) or `updates`; `tag` per incident; `visibility: public`. `data.type` is unchanged except for the new `incident_new`. |

### Frontend Changes
- Mobile (`replit-android` v1.12.6) creates the two channels, ships the
  alarm, and opens every notification where it belongs. See that
  repository's `CHANGELOG.md`.

### Testing
- Channels: a fire uses `fire_alerts`, the `fire_alarm` sound, priority max,
  public on the lock screen, with its tag. Anything else uses `updates` and the
  phone's tone. Both are high priority.
- Who hears about a new fire: Fire Volunteer ↔ BFP both ways; fire + medical;
  police alone; barangay + police; nothing asked → nobody. The staff query
  takes responders and coordinators and active accounts only. The push rings,
  carries `incident_new` and the incident, and is tagged. No staff → no push
  and no row. Staff without a phone still get the Alerts row.
- Only the report that makes the incident alerts staff (`report_count` 1 vs
  2). A failing staff alert does not fail the report.
- Neighbours: a first alert rings, a reminder does not, both carry the same
  tag.
- Why push will not start: a laptop path, JSON that isn't JSON, and a key
  Firebase refuses each give their own `push_detail`, and none quotes the key.
  Quotes around a pasted key and doubled backslashes are undone. A working
  push has no detail.
- Result: 503 backend tests pass (23 new); `ruff` clean; `mypy` clean apart
  from the pre-existing `app/services/ai_summary.py:74`.

### Regression Check
Full backend suite passes. Citizens' report updates and neighbour alerts
carry the same `data` as before, so older app builds still open them. **To
make any of this reach a phone, Render needs `FCM_CREDENTIALS_JSON`** (the
whole service-account file, pasted as it is). Check `/health/ready` for
`"push": "ok"` after the redeploy.

---

## v1.12.5 — 5 October 2026 — AI summaries for coordinators, and the PDF in a browser

### Changes

**Added**
- **AI summaries list** for Fire Volunteer and BFP coordinators (and Admin):
  every incident a team has filed its Post-Incident Report for, newest first,
  each with its newest summary. No gate on how many citizens reported it.
- **Nobody asks for a summary.** One is still written when each team files
  (as since v1.12.0). The list now also writes any that are owed: an
  incident with no summary (the ones from before the AI key was set), or one
  whose newest report came after its summary (a rewrite that failed). It
  starts them after answering, at most 10 per load, and once per incident in
  ten minutes, so pulling to refresh never starts a second copy.
- **The PDF, downloaded in the phone's browser.** A browser cannot send the
  sign-in, so the app asks for a link that works for five minutes, for one
  incident, for the person it was made for. The link is HMAC-signed (key
  derived from `SUPABASE_JWT_SECRET`, or the service-role key if that is
  unset); nothing is stored. The download checks again that the account is
  active staff who can see the incident. The PDF is still built at each
  download, so it carries every report filed by then. Its file name is
  readable: `Fire-report-Area-3-2026-10-05.pdf`.

**Modified**
- `GET /incidents/{id}/report.pdf` shares its PDF building with the new
  download; it behaves the same.

### Files Changed
- New: `app/services/report_links.py`, `tests/test_ai_summaries.py`.
- `app/api/routes/ai.py` (`summaries_router`, `GET /ai-summaries`),
  `app/api/routes/incident_reports.py` (`report-link`, `report-download`),
  `app/services/ai_summary.py` (the owed-summary rule, the ten-minute claim,
  the list query), `app/schemas/ai.py` (`SummarizedIncident`,
  `ReportLinkResponse`), `app/api/routes/__init__.py`.
- `pyproject.toml`, `uv.lock`, `app/core/config.py`, `admin-web/package.json`,
  `observer-web/package.json` — version 1.12.5.

### Database Changes
None. (v1.12.4's `20261005090000_responder_accounts.sql` must still be
applied before this backend deploys. See below.)

### API Changes
| Endpoint | Change |
|---|---|
| `GET /ai-summaries?limit=50` | **New.** Coordinators and Admin (observers, responders → 403). `[{area_id, designation, status, reported_at, closed_at, reports_filed, teams[], last_filed_at, state, summary_id, summary_text, model, generated_at}]`, newest first, scoped to what the caller's agency sees. `state`: `ready` / `writing` (being written; an older summary is still returned meanwhile) / `unavailable` (no AI key). |
| `POST /incidents/{id}/report-link` | **New.** Visibility-checked staff → `{path, expires_at}`; `path` is relative to the API base and carries its signature. |
| `GET /incidents/{id}/report-download?token=` | **New. No Authorization header.** Streams the PDF (`Cache-Control: private, no-store`). Expired → 410, tampered or for another incident → 403, account deactivated or no longer able to see the incident → 403. Each refusal is plain text, since a browser shows it. |

### Frontend Changes
- Mobile (`replit-android` v1.12.5): menu → **AI summaries** for Fire
  Volunteer and BFP coordinators. A list of "Summarized incident — 10/5/2026";
  each opens as a note with **Download PDF**. See that repository's
  `CHANGELOG.md`.

### Testing
- The link: works within five minutes for its incident and user; expires
  after; refused for another incident, with the user, expiry or signature
  changed, or malformed; URL-safe; signs without the JWT secret.
- What is owed: a summary after the last report is ready; none, or one
  older than the newest report, is owed (`writing`, or `unavailable` with no
  key); a summary is started once in ten minutes.
- The list: a coordinator sees each incident and its teams; a missing
  summary is started without anyone asking and not again on refresh; an
  outdated one is shown while it is rewritten; nothing starts without a key; a
  backlog goes 10 per load with no repeats; a fire coordinator's query covers
  both fire agencies; Admin's covers all; police, responders and citizens are
  refused (403) before any query; no sign-in → 401.
- The download: link → PDF in a browser with no sign-in, readable file name,
  `no-store`; no link for another agency's incident; a deactivated account's
  link stops at once; a link does not open another incident; an expired one
  says so in words (410); the file name is the incident's Philippine day.
- Result: 480 backend tests pass (34 new); `ruff` clean; `mypy` clean apart
  from the pre-existing `app/services/ai_summary.py:74` (`ph_time`, moved two
  lines by an import, not otherwise touched).

### Regression Check
Full backend suite passes. Filing a Post-Incident Report still writes the
summary exactly as before. The ten-minute note it now leaves only stops the
list from starting a duplicate. `report.pdf` is unchanged for the Admin
Console.

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
