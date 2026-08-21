# RepLiT Backend

Production backend for **RepLiT** — the Pasay City Fire Volunteer Coordination
Platform (M2STZ Capstone, v8). FastAPI + Supabase (PostgreSQL/PostGIS),
built and managed with [uv](https://docs.astral.sh/uv/).

> Scope note: this repository is the backend (plus minimal placeholder UIs used only
> to verify integration). Production mobile (Flutter) and web (React) UIs are built
> separately by the frontend team.

## Prerequisites

- **Python 3.14** (the whole team uses this exact version; pinned via `.python-version`)
- **uv** 0.11+ — https://docs.astral.sh/uv/getting-started/installation/
- **Docker Desktop** (optional, for containerized runs)

## Setup

```powershell
# From the project root (H:\replit_backend)
uv python pin 3.14      # ensures the pinned interpreter
uv sync                 # creates .venv and installs all dependencies
Copy-Item .env.example .env
```

Then fill in `.env` — at minimum the `SUPABASE_*` keys and `DATABASE_URL` (use the
**transaction** pooler URI, port 6543). Every other section degrades gracefully: the
`*_configured` properties in `app/core/config.py` report readiness and each feature
raises a clear error only if used without its credentials.

## Run locally

```powershell
uv run uvicorn app.main:app --reload     # or: make dev
uv run pytest                            # 113 tests, no DB required
uv run ruff check app tests
uv run mypy app
```

## Run in Docker

Build from the **repository root** — the Dockerfile copies `pyproject.toml`,
`uv.lock` and `app/`, so any other build context fails on the first `COPY`.

```bash
docker compose up -d --build
```

```bash
docker compose logs -f api
```

Notes:

- **`.env` is read at runtime**, not baked in (`env_file:` in `docker-compose.yaml`).
  The image contains no secrets.
- **FCM credentials** are mounted, not copied: `./secrets` → `/app/secrets:ro`, and
  `FCM_CREDENTIALS_FILE` resolves relative to `/app`. On a host without volumes
  (e.g. DigitalOcean App Platform) set `FCM_CREDENTIALS_JSON` to the raw JSON on one
  line and drop the mount.
- **One worker, deliberately.** `app/realtime/manager.py` holds its WebSocket
  subscriber registry in process memory and the 60 s neighborhood scheduler in
  `app/workers/neighborhood.py` is per-process. A second worker would receive none of
  the first's broadcasts and would double-send neighborhood alerts. Scale by replica
  behind a shared pub/sub backend, never by `--workers`.
- **Migrations are not applied by the image.** Run `supabase db push` against the
  project; `supabase/` is excluded from the build context.
- The `HEALTHCHECK` hits `/health` (no auth, no DB). `/health/ready` additionally
  probes the database and is the right target for a load balancer.

## Layout

```
app/api/routes/     FastAPI routers (23)
app/services/       domain logic (clustering, incident lifecycle, AI summary, PDF)
app/workers/        the 60 s neighborhood notification scheduler
app/integrations/   Supabase, Twilio, Didit, Brevo, FCM, Anthropic clients
app/realtime/       WebSocket manager + event broadcasting
supabase/migrations 19 SQL migrations — the authoritative schema
admin-web/          admin console (React 18 + Vite), deployed separately
```