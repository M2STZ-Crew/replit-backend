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