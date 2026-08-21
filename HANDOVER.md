# Setting the project up on another laptop

Everything below assumes a fresh Windows machine. Estimated time: ~30 min, most of
it waiting on installers.

---

## Read this first — two things that will waste your afternoon

**1. `git clone` gives you an empty project.** GitHub's default branch for this repo is
`main`, which contains **one file** (`README.md`) and has a completely unrelated commit
history — no shared ancestor with the real work. All 13 commits of actual code are on
**`safe-commits`**. Clone and then switch branches, as in Step 2.

**2. Four things are not in git and will not arrive with a clone.** They must be moved
by hand — see Step 3. The mobile app in particular is in **no repository at all** and
exists only on the original laptop.

---

## What travels, and what doesn't

| | Where it lives | Arrives with `git clone`? |
|---|---|---|
| Backend source, 19 migrations, tests | `safe-commits` branch | yes |
| `admin-web/` source + `package-lock.json` | `safe-commits` branch | yes |
| `uv.lock` (exact dependency versions) | `safe-commits` branch | yes |
| **`.env`** — 34 keys, all backend secrets | gitignored | **no — copy by hand** |
| **`secrets/firebase-service-account.json`** | gitignored | **no — copy by hand** |
| **Flutter mobile app** | `Replit_mobile_dev/replit_app`, not a git repo | **no — copy the folder** |
| `admin-web/.env` | gitignored | no — but recreate from `.env.example` in 5 s |
| `node_modules/`, `.venv/` | gitignored | no — rebuilt by `npm ci` / `uv sync` |
| Supabase CLI link (`supabase/.temp/`) | gitignored | no — re-link, Step 6 |

Good news: nothing in the tracked code hardcodes a drive letter or an absolute path.
`FCM_CREDENTIALS_FILE=secrets/firebase-service-account.json` is relative, so it resolves
correctly on any machine as long as the file is in place.

---

## Step 1 — Install the tooling

| Tool | Version | Notes |
|---|---|---|
| Git | any recent | |
| Python | **3.14** | pinned in `.python-version`; the team uses this exact version |
| uv | **0.11+** | https://docs.astral.sh/uv/getting-started/installation/ |
| Node.js | 20+ | for `admin-web` only |
| Supabase CLI | 2.x | https://supabase.com/docs/guides/cli |
| Docker Desktop | optional | only for `docker compose` and `supabase db dump` |
| Flutter | Dart SDK ^3.11.1 | only if working on mobile |

## Step 2 — Clone the right branch

```bash
git clone https://github.com/M2STZ-Crew/replit-backend.git
cd replit-backend
git checkout safe-commits
```

Confirm you got the real thing — you should see 159 files and `ddfda4f` (or later) at
the tip:

```bash
git log --oneline -1
```

If the repo is private, the new team member needs to be added as a collaborator on the
`M2STZ-Crew` organisation first, or the clone will 404.

## Step 3 — Move the secrets across

Two files, from the original laptop:

```
.env                                 -> repo root
secrets/firebase-service-account.json -> repo root, create the secrets/ folder
```

**Do not send these over Messenger, Viber, email, or a chat paste.** They include the
Supabase **service-role key**, which bypasses every RLS policy in the database, plus the
Twilio, Brevo, Didit, and Anthropic credentials. Anyone holding that file has full read
and write access to all user data.

Use one of:

- a password manager with secure sharing (1Password, Bitwarden Send)
- a 7-Zip archive with AES-256 encryption, transferred over one channel with the
  password given over a different one (e.g. file by Drive, password spoken in person)

Never ask an AI assistant to relay these values, and don't paste them into a chat
transcript — the whole file is credentials.

Then create the dashboard's env file — this one holds nothing secret:

```bash
cd admin-web
copy .env.example .env    # VITE_API_BASE=http://localhost:8000
cd ..
```

## Step 4 — Install backend dependencies

```bash
uv python pin 3.14
uv sync
```

## Step 5 — Prove the install before touching the database

The test suite is fully hermetic — no database, no network. If this passes, the Python
side is sound and any later failure is configuration, not setup.

```bash
uv run pytest          # expect: 113 passed
uv run ruff check app tests
uv run mypy app
```

## Step 6 — Connect to Supabase

The CLI link lives in the gitignored `supabase/.temp/`, so every machine links itself.
Ask the project owner for the project ref.

```bash
supabase login
supabase link --project-ref <PROJECT_REF>
supabase migration list --linked
```

The last migration listed must be **`20260811120100`**, and every row should show the
same value in the local and remote columns. If remote entries are missing, the schema is
behind — run `supabase db push`.

The new team member also needs an invite to the Supabase organisation to see the project
in the dashboard.

## Step 7 — Run it

Backend:

```bash
uv run uvicorn app.main:app --reload
```

Check both probes:

- http://localhost:8000/health — process is alive (no auth, no DB)
- http://localhost:8000/health/ready — **also proves the database connection works**
- http://localhost:8000/docs — the full API surface

Dashboard, in a second terminal:

```bash
cd admin-web
npm ci
npm run dev
```

Opens on http://localhost:5173, which is already in the backend's `CORS_ORIGINS`. Log in
with an **admin** account — the console rejects other roles.

### Or run the backend in Docker

```bash
docker compose up -d --build
docker compose logs -f api
```

`.env` is read at runtime and `./secrets` is mounted read-only, so both must exist first
(Step 3). See the Docker notes in `README.md`.

## Step 8 — Mobile app (only if you need it)

Not in any repository. Copy `Replit_mobile_dev/replit_app` from the original laptop,
then:

```bash
flutter pub get
```

Recreate its `.env` — separate from the backend's, and it needs only:

```
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

(The original also carries an `OPENWEATHERMAP_API_KEY` for a weather feature that isn't
part of the v8 scope.)

Be aware of what you're inheriting: `lib/main.dart` is still the **stock Flutter counter
template**. The `lib/features/` folders (auth screens, api client, entities) exist but
nothing is wired to them, and the app talks to Supabase directly rather than through
this backend. Treat it as a scaffold, not a working app.

---

## Verification checklist

- [ ] `git log --oneline -1` shows `ddfda4f` or later, on `safe-commits`
- [ ] `uv run pytest` → 113 passed
- [ ] `uv run mypy app` → no issues in 78 source files
- [ ] `/health` returns 200
- [ ] `/health/ready` returns 200 with the database reported connected
- [ ] `supabase migration list --linked` ends at `20260811120100`, local == remote
- [ ] `admin-web` loads on :5173 and an admin login succeeds
- [ ] `.env` has all 34 keys and `secrets/firebase-service-account.json` exists

---

## Two repo problems worth fixing during the move

**Change the default branch.** While `main` stays the default, every clone by every new
team member starts with one file and an unrelated history. On GitHub: *Settings →
General → Default branch → switch to `safe-commits`*. The empty `main` can then be
deleted.

**Put the Flutter app in git.** It currently exists on exactly one laptop with no
history and no backup. A `git init`, a private repo, and one push removes a single point
of failure.
