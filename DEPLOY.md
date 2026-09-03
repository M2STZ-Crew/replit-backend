# Deploying RepLiT for free

Aimed at getting a working URL you can show an adviser. Everything below is on a
genuinely free tier with no credit card.

| Piece | Host | Free tier | Cost |
|---|---|---|---|
| FastAPI backend | **Render** (Docker) | 512 MB, sleeps when idle | $0 |
| Admin dashboard | **Cloudflare Pages** or Vercel | unlimited static builds | $0 |
| Database + storage | **Supabase** (already there) | 500 MB DB, 1 GB storage | $0 |
| Mobile app | **APK file** on Drive, or Firebase App Distribution | — | $0 |

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
2. **New → Blueprint**, choose `M2STZ-Crew/replit-backend`, branch
   **`safe-commits`** (not `main`, which is the near-empty branch).
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

## 3. Mobile app

There is no free way to publish to the Play Store (Google charges a one-off $25),
but you do not need the store for a demo.

```bash
flutter build apk --release
```

The APK lands in `build/app/outputs/flutter-apk/app-release.apk`. Two ways to
share it:

- **Google Drive link** — simplest. The installer has to allow "install from
  unknown sources", which is normal for a capstone build.
- **Firebase App Distribution** — free, and testers get an install prompt rather
  than a raw file. Worth it if several panel members want it on their phones.

Before building, point the app at the deployed backend in
`Replit_mobile_dev/replit_app/.env`:

```
API_BASE_URL=https://<your-service>.onrender.com
```

Not `10.0.2.2` — that only means anything to an Android emulator talking to your
own machine.

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
- [ ] `PUBLIC_BASE_URL` is the Render URL, not localhost
- [ ] `CORS_ORIGINS` contains the dashboard URL
- [ ] `FCM_CREDENTIALS_JSON` set, `FCM_CREDENTIALS_FILE` unset
- [ ] Dashboard loads and an admin login succeeds
- [ ] Refreshing the dashboard on `/login` does not 404
- [ ] Mobile `.env` points at the Render URL, APK built
- [ ] Backend woken up a few minutes before the demo
