# syntax=docker/dockerfile:1

# ============================================================================
# RepLiT backend — FastAPI + asyncpg (Supabase/PostGIS), Python 3.14
# Build from the REPOSITORY ROOT:  docker build -t replit-backend .
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: builder — resolve and install dependencies into /app/.venv
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

# Pinned uv binary (matches the local uv version for reproducibility).
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Compilers are only needed if a dependency has no cp314 wheel (pillow, reportlab,
# asyncpg and grpcio all publish them today). Kept in the builder so the runtime
# image never carries a toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a source-only change doesn't reinstall the world.
# --no-install-project matches [tool.uv] package = false in pyproject.toml.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: runtime — copy the venv, add source, drop privileges
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

# The venv is relocated to the identical path, so its interpreter symlinks and
# console scripts stay valid.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser app ./app

# Secrets are NOT baked into the image. FCM needs either a mounted file
# (FCM_CREDENTIALS_FILE, see docker-compose.yaml) or the raw JSON in
# FCM_CREDENTIALS_JSON for platforms without volumes.

USER appuser

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health').status==200 else 1)"

# Single worker is deliberate, not a default left unchanged. app.realtime.manager
# keeps its WebSocket subscriber registry in process memory, so a second worker
# would silently receive none of the other's broadcasts. Scaling out needs a
# shared pub/sub backend first — until then scale by replica, not by worker.
# The 60 s neighborhood scheduler (app.workers.neighborhood) is likewise
# per-process and would double-send if run twice.
#
# Wrapped in `sh -c` so $PORT expands: managed hosts (Render, Koyeb, Cloud Run)
# assign the port at runtime and health-check that port only. `exec` replaces the
# shell, so uvicorn stays PID 1 and still receives SIGTERM for a clean shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app \
     --host 0.0.0.0 --port ${PORT:-8000} \
     --workers 1 \
     --proxy-headers --forwarded-allow-ips '*' \
     --no-access-log"]
