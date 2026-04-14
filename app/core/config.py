"""
config.py – Application configuration via Pydantic Settings.
All values are loaded from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────
    APP_NAME: str = "RepLit API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # ── Supabase ─────────────────────────────────────────────
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    DATABASE_URL: str               # Direct PostgreSQL connection

    # ── JWT ──────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Claude AI ────────────────────────────────────────────
    CLAUDE_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

    # ── Firebase ─────────────────────────────────────────────
    FCM_SERVER_KEY: str = ""
    FIREBASE_CREDENTIALS_PATH: str = "firebase-credentials.json"

    # ── Storage ──────────────────────────────────────────────
    SUPABASE_STORAGE_BUCKET: str = "incident-media"

    # ── Clustering ───────────────────────────────────────────
    INCIDENT_CLUSTER_RADIUS_METERS: int = 150

    # ── Sentry ───────────────────────────────────────────────
    SENTRY_DSN: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse comma-separated ALLOWED_ORIGINS into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    Return cached Settings instance.
    Using lru_cache ensures .env is only read once.
    """
    return Settings()