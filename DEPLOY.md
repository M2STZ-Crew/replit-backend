# Deploying RepLiT for free

Aimed at getting a working URL you can show an adviser. Everything below is on a
genuinely free tier with no credit card.

| Piece | Host | Free tier | Cost |
|---|---|---|---|
| FastAPI backend | **Render** (Docker) | 512 MB, sleeps when idle | $0 |
| Admin Console (`admin-web`) | **Vercel** or Cloudflare Pages | unlimited static builds | $0 |
| Observer Console (`observer-web`) | same host, **separate project** | unlimited static builds | $0 |
| Database + storage | **Supabase** (already there) | 500 MB DB, 1 GB storage | $0 |
| Mobile app | **APK file** on Drive, or Firebase App Distribution | — | $0 |

Four deployments in total. The two consoles are separate SPAs by design (Master
Context v10 §3.1), so they are two projects on the host, not one project with a
role switch.

---

## Read this before you start

**Your Supabase project expires this month.** Deploying against a database that
is about to disappear will break the demo at the worst moment. Sort this first:

- Cheapest fix: create a **new free Supabase project**, run `supabase db push`
  against it to rebuild the schema from the 19 migrations, then reload data using
  `RESTORE.md` from the backup folder. Free projects pause after a week of
  inactivity but do not expire — opening the dashboard wakes them.
- Then re-point `DATABASE_URL`, `SUPABASE_*` and the mobile app's `.env` at it.

**Render's free instance sleeps after ~15 minutes of no traffic**, and the next
request takes roughly 50 seconds to wake it. Two consequences:

1. Open the URL a minute or two before showing anyone, so the adviser never sees
   a spinner.
2. While asleep, the 60-second neighbourhood-alert scheduler does not run. Keep a
   browser tab pointed at the dashboard during the demo to hold it awake.

---

## 1. Backend on Render

The repo already contains `render.yaml`, so this is a blueprint deploy rather
than a pile of dashboard settings.

1. Sign in at [render.com](https://render.com) with GitHub — no card required.
2. **New → Blueprint**, choose `M2STZ-Crew/replit-backend`, branch **`main`**.

   > Older instructions said `safe-commits`. That was true while `main` was a
   > near-empty decoy branch; `safe-commits` has since been merged into `main`,
   > which is now the trunk. If your service was created before that, open
   > **Settings → Branch** in Render and switch it to `main` — otherwise pushes
   > to `main` build nothing and the service quietly serves older code.
3. Render reads `render.yaml`, finds the root `Dockerfile`, and asks you to fill
   in every variable marked `sync: false` — 19 of them. Paste from your local
   `.env`, with three that must **change**:

   | Variable | Value on Render |
   |---|---|
   | `PUBLIC_BASE_URL` | the service's own URL, e.g. `https://replit-backend.onrender.com` |
   | `CORS_ORIGINS` | the dashboard's URL once step 2 is done |
   | `FCM_CREDENTIALS_JSON` | the whole service-account JSON on one line |

   Use `FCM_CREDENTIALS_JSON`, **not** `FCM_CREDENTIALS_FILE` — a free instance
   has no writable disk to hold the file. Leave `FCM_CREDENTIALS_FILE` unset.

   For `DATABASE_URL` use the **transaction pooler** URI (port 6543). A free
   instance gets few connections and the pooler is what keeps that workable.

4. Deploy. First build takes 5–10 minutes. When it finishes, check:

   - `https://<your-service>.onrender.com/health` → `200`
   - `https://<your-service>.onrender.com/health/ready` → `{"database":"ok"}`
   - `https://<your-service>.onrender.com/docs` → the full API

`/health/ready` is the one that matters; it actually connects to Postgres, so a
200 there proves the environment variables are right.

## 2. Dashboard on Cloudflare Pages

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** →
   **Create → Pages → Connect to Git**.
2. Pick the same repo and branch, then set:
   - **Root directory**: `admin-web`
   - **Build command**: `npm run build`
   - **Output directory**: `dist`
3. Add an environment variable: `VITE_API_BASE` = your Render URL.
4. Deploy.

`admin-web/public/_redirects` is already committed, which is what stops a refresh
on `/login` from returning 404. Vercel works identically and reads the committed
`admin-web/vercel.json`.

**Then go back to Render** and set `CORS_ORIGINS` to the Pages URL, e.g.
`https://replit-admin.pages.dev`. Until you do, the browser blocks every API call
and the dashboard looks broken while the backend looks healthy.

### The Observer Console

The Observer Console (`observer-web`, for Police, Medical and Barangay team
captains — Master Context v10 §2.6) is a **second, separate project on the same
host**, never a second branch of the Admin Console. On Vercel:

1. **Add New → Project**, pick `M2STZ-Crew/replit-backend` again.
2. Set **Root Directory** to `observer-web`. Vercel then reads the committed
   `observer-web/vercel.json`, which already supplies the build command, the
   `dist` output directory and the SPA rewrite that stops a refresh on `/login`
   returning 404. Leave the build settings alone.
3. Environment variables: `VITE_API_BASE` (the Render URL) and
   `VITE_MAPBOX_TOKEN`.
4. Deploy.

Then wire the three cross-links, or pieces break quietly:

- add its URL to `CORS_ORIGINS` on Render, comma-separated after the Admin
  Console's — until you do, every request from the console is blocked by the
  browser while the backend itself looks perfectly healthy;
- set `VITE_OBSERVER_URL` on the Admin Console project to it, so the Admin
  Console can point an observer who signs in there to the right place;
- set `OBSERVER_CONSOLE_URL` in the mobile app's `env.json` for the same reason.

Changing an environment variable on Vercel does **not** rebuild by itself — a
Vite variable is inlined at build time, so redeploy after editing one or the old
value stays in the bundle.

### A note on the Mapbox token

`VITE_MAPBOX_TOKEN` is readable inside the deployed JavaScript bundle. That is
unavoidable for any browser map and is why Mapbox issues *public* `pk.` tokens,
but it means a deployed console publishes whatever token you give it.

Use **two tokens**:

- a **URL-restricted** token for the two web consoles, scoped to their
  deployed origins;
- the **unrestricted** one for the mobile binary only.

One token cannot safely do both. Mapbox enforces URL restrictions by checking
the `Referer` header, which a native app never sends, so a restricted token
makes the phone's map silently fall back to plain OpenStreetMap tiles.

## 3. Mobile app

The app is not deployed to a host. You compile an APK with the backend URL
**baked in at build time** and hand people the file. There is no settings screen
that can change the URL afterwards, so a wrong value means rebuilding.

> The Flutter project is `M2STZ-Crew/replit-android`, cloned locally at
> `C:\Users\Admin\AndroidStudioProjects\mobile`. It is **not**
> `H:\Replit_mobile_dev\replit_app`, which is an abandoned parallel scaffold
> that also has the `replit-android` remote configured. Earlier versions of this
> file pointed at that dead copy and at a `.env` / `API_BASE_URL` pair the real
> app has never read.

### 3.1 Point it at the deployed backend

Edit `env.json` in the Flutter project root — gitignored, so it never leaves
your machine and has to be recreated per laptop from `env.example.json`:

```json
{
  "MAPBOX_TOKEN": "pk....",
  "REPLIT_API_BASE": "https://<your-service>.onrender.com",
  "OBSERVER_CONSOLE_URL": "https://<your-observer-console>.vercel.app"
}
```

`REPLIT_API_BASE` must be the Render URL, not `10.0.2.2` — that address only
means anything to an Android emulator talking to the machine it runs on.

### 3.2 Build

```bash
flutter build apk --release --dart-define-from-file=env.json
```

**`--dart-define-from-file=env.json` is the step everyone forgets.** Without it
the build still succeeds, but every value falls back to its compiled default —
`http://10.0.2.2:8000` for the API and an empty Mapbox token. The APK installs,
opens, shows the login screen, and then fails every request with no visible
reason. If a tester reports "it just spins", this is almost always why.

The file lands at `build/app/outputs/flutter-apk/app-release.apk`, around 55 MB.

### 3.3 Signing

`android/app/build.gradle.kts` still carries the Flutter template's TODO:

```kotlin
signingConfig = signingConfigs.getByName("debug")
```

A debug-signed release APK installs and runs normally, and Firebase push still
works — FCM does not require a registered SHA-1 fingerprint. That is enough for
a demo and for pilot handsets.

What it costs: that build can never go to the Play Store, and it can never be
updated by a build signed with a different key. Android treats a changed signing
key as a different application, so testers would have to uninstall first. Before
any real distribution, generate a keystore — the key and its password must
belong to the team, so it is not something to hand to an assistant or commit:

```bash
keytool -genkey -v -keystore %USERPROFILE%\replit-release.jks -storetype JKS -keyalg RSA -keysize 2048 -validity 10000 -alias replit
```

Then add `android/key.properties` and a `release` signing config. Both are
gitignored. **Back the keystore up somewhere permanent** — losing it means never
being able to update the app again.

### 3.4 Distribute

**Google Drive link.** Upload `app-release.apk`, share the link, and tell people
they will have to allow "install from unknown sources" once — Android shows this
prompt for any app not from the Play Store, and it is normal for a capstone
build.

**Firebase App Distribution** is the alternative: free, already half-configured
because the project uses FCM, and testers get a proper install prompt plus
notifications of new builds. Worth it once more than two or three people need
the app.

### 3.5 Once the backend is on HTTPS

`android/app/src/main/res/xml/network_security_config.xml` permits cleartext
HTTP to the emulator aliases and one hard-coded LAN IP. HTTPS needs no entry at
all, so once the Render URL is the only backend in use the whole
`domain-config` block can be deleted. Leaving it is not dangerous — it is an
allow-list of four specific addresses, not a blanket opt-out — but deleting it
proves the release build cannot talk to anything unencrypted.

---

## Other hosts, and why not

| Host | Verdict |
|---|---|
| **Fly.io** | No longer has a genuine free allowance; needs a card and burns trial credit. |
| **Railway** | $5 trial credit, then paid. Fine for a week, not for a pilot. |
| **Google Cloud Run** | Generous free tier and it does support WebSockets, but it scales to zero, which stops the neighbourhood scheduler. Also needs a card. |
| **Oracle Cloud Always Free** | The best long-term option — a genuinely always-free ARM VM that never sleeps, so the scheduler runs continuously. Needs a card for signup and far more setup. Worth it for the actual pilot, overkill for showing an adviser. |
| **Vercel / Netlify (backend)** | Serverless. Cannot hold a WebSocket open and cannot run APScheduler. Fine for the dashboard, wrong for this API. |

If the pilot goes to real Fire Volunteers, move the backend to Oracle Always Free
or a $6 DigitalOcean droplet — Section 3.1 of the master context assumes a droplet
anyway, and the sleep behaviour is not acceptable for emergency reporting.

---

## Checklist

- [ ] Supabase project not expiring mid-demo
- [ ] Render service live, `/health/ready` returns `database: ok`
- [ ] Render is building the **`main`** branch, not `safe-commits`
- [ ] `PUBLIC_BASE_URL` is the Render URL, not localhost
- [ ] `CORS_ORIGINS` contains **both** console URLs, comma-separated
- [ ] `FCM_CREDENTIALS_JSON` set, `FCM_CREDENTIALS_FILE` unset
- [ ] Admin Console loads and an admin login succeeds
- [ ] Observer Console loads; a `police` / `medical` / `barangay` sub-admin can
      sign in, and anyone else is turned away
- [ ] Refreshing either console on `/login` does not 404
- [ ] `VITE_OBSERVER_URL` set on the Admin Console project
- [ ] Web consoles use a **URL-restricted** Mapbox token; the mobile build uses
      the unrestricted one
- [ ] Mobile `env.json` has the Render URL in `REPLIT_API_BASE` and the observer
      URL in `OBSERVER_CONSOLE_URL`
- [ ] APK built **with `--dart-define-from-file=env.json`**, installed on a real
      phone, and a login against the deployed backend succeeds
- [ ] Backend woken up a few minutes before the demo
