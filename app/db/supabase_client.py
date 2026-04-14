"""
supabase_client.py – Initializes the Supabase Python SDK clients.

Two clients are provided:
  - supabase_client: Uses ANON_KEY  → respects RLS (for user operations)
  - supabase_admin:  Uses SERVICE_ROLE_KEY → bypasses RLS (for backend ops)
"""

from supabase import create_client, Client
from app.core.config import get_settings

settings = get_settings()

# ── Public client (respects Row Level Security) ──────────────
supabase_client: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_ANON_KEY,
)

# ── Admin client (bypasses Row Level Security) ───────────────
# ⚠️ Only use this for trusted server-side operations
supabase_admin: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY,
)