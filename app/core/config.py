"""Application configuration via Pydantic Settings.

Single source of truth for all runtime configuration and secrets, loaded from
environment variables then a local ``.env`` file, accessed via :func:`get_settings`.
No hardcoded secrets anywhere (master context Section 5, Section 13).

Optional integration sections (Supabase, database, Twilio) default to empty so the
app always boots; ``*_configured`` properties report readiness, and the consuming
modules raise a clear error if a feature is used without its configuration.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Core application (Phase 1) -----
    environment: Environment = Field(
        default="development",
        description='Deployment environment: "development" | "staging" | "production".',
    )
    app_name: str = Field(default="RepLiT Backend", description="Human-readable app name.")
    app_version: str = Field(default="0.1.0", description="Semantic version of the build.")
    host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    port: int = Field(default=8000, ge=1, le=65535, description="Uvicorn bind port.")

    log_level: LogLevel = Field(default="INFO", description="Minimum log level emitted.")
    log_json: bool | None = Field(
        default=None,
        description="Force JSON logs; None auto-enables JSON for non-development.",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins.",
    )

    # ----- Supabase (Phase 2/3) -----
    supabase_url: str = Field(default="", description="Project URL, e.g. https://<ref>.supabase.co.")
    supabase_anon_key: str = Field(default="", description="Public anon key (clients).")
    supabase_service_role_key: str = Field(
        default="", description="Service-role key — SERVER ONLY, bypasses RLS."
    )
    supabase_jwt_secret: str = Field(
        default="", description="Legacy HS256 JWT secret (fallback when tokens aren't JWKS-signed)."
    )
    supabase_project_ref: str = Field(default="", description="20-char project reference id.")
    database_url: str = Field(
        default="", description="Postgres connection string (use the transaction pooler URI)."
    )

    # ----- Database pool (Phase 3) -----
    db_pool_min_size: int = Field(default=1, ge=0, description="asyncpg pool minimum size.")
    db_pool_max_size: int = Field(default=10, ge=1, description="asyncpg pool maximum size.")
    db_command_timeout: float = Field(
        default=30.0, gt=0, description="Per-command timeout (seconds) for DB queries."
    )

    # ----- JWT validation (Phase 3) -----
    jwt_audience: str = Field(default="authenticated", description="Expected JWT 'aud' claim.")
    jwks_cache_ttl_seconds: int = Field(
        default=600, ge=0, description="How long to cache Supabase JWKS keys."
    )

    # ----- Twilio Verify (Phase 3) -----
    twilio_account_sid: str = Field(default="", description="Twilio Account SID.")
    twilio_auth_token: str = Field(default="", description="Twilio Auth Token (secret).")
    twilio_verify_service_sid: str = Field(
        default="", description="Twilio Verify Service SID (VA...)."
    )

    # ----- Didit.me KYC (Phase 4) -----
    didit_api_key: str = Field(default="", description="Didit.me API key (x-api-key).")
    didit_base_url: str = Field(
        default="https://verification.didit.me",
        description="Didit.me verification API base URL.",
    )
    didit_workflow_id: str = Field(
        default="", description="Didit.me workflow id for the National ID + selfie flow."
    )

    didit_webhook_secret: str = Field(
        default="", description="Didit.me webhook shared secret (HMAC signature verification)."
    )

    # ----- Brevo email (Phase 4) -----
    brevo_smtp_host: str = Field(default="smtp-relay.brevo.com", description="Brevo SMTP host.")
    brevo_smtp_port: int = Field(default=587, ge=1, le=65535, description="Brevo SMTP port.")
    brevo_smtp_user: str = Field(default="", description="Brevo SMTP login.")
    brevo_smtp_key: str = Field(default="", description="Brevo SMTP key (password).")
    email_from: str = Field(default="", description="Verified sender email address.")
    email_from_name: str = Field(default="RepLiT", description="Sender display name.")
    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL of this backend (used to build email verification links).",
    )

    # ----- Firebase Cloud Messaging (Phase 5) -----
    fcm_credentials_file: str = Field(
        default="", description="Path to the Firebase service-account JSON file."
    )
    fcm_credentials_json: str = Field(
        default="", description="Raw service-account JSON (alternative to a file, for deploys)."
    )

    # ----- Incident reporting (Phase 6) -----
    report_max_photo_bytes: int = Field(default=5_242_880, gt=0)   # 5 MB
    report_max_video_bytes: int = Field(default=1_572_864, gt=0)   # 1.5 MB
    gps_discrepancy_threshold_m: float = Field(
        default=100.0, gt=0, description=
        "Device-vs-EXIF distance that flags a discrepancy (Section 3.1)."
    )

    # ----- Verification percents (Sections 2, 3.2, 3.3) -----
    phone_verification_percent: int = Field(default=40, ge=0, le=100)
    email_verification_percent: int = Field(default=10, ge=0, le=100)
    id_verification_percent: int = Field(default=50, ge=0, le=100)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Uppercase/trim the log level so values like ``"info"`` are accepted."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    # ----- Derived helpers -----
    @property
    def cors_origins_list(self) -> list[str]:
        """Return the parsed CORS origins, with blank entries stripped."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        """Return True when running in the development environment."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.environment == "production"

    @property
    def use_json_logs(self) -> bool:
        """Resolve the effective log format (explicit LOG_JSON else non-dev => JSON)."""
        if self.log_json is not None:
            return self.log_json
        return self.environment != "development"

    @property
    def gotrue_url(self) -> str:
        """Base URL of the Supabase Auth (GoTrue) REST API."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def storage_url(self) -> str:
        """Base URL of the Supabase Storage REST API."""
        return f"{self.supabase_url.rstrip('/')}/storage/v1"

    @property
    def jwks_url(self) -> str:
        """URL of the Supabase JWKS (public keys) endpoint."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def supabase_configured(self) -> bool:
        """True when the core Supabase credentials are present."""
        return bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)

    @property
    def database_configured(self) -> bool:
        """True when a database connection string is present."""
        return bool(self.database_url)

    @property
    def twilio_configured(self) -> bool:
        """True when all Twilio Verify credentials are present."""
        return bool(
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_verify_service_sid
        )
    
    @property
    def didit_configured(self) -> bool:
        """True when Didit.me KYC credentials are present."""
        return bool(self.didit_api_key and self.didit_workflow_id)

    @property
    def brevo_configured(self) -> bool:
        """True when Brevo SMTP credentials and sender are present."""
        return bool(self.brevo_smtp_user and self.brevo_smtp_key and self.email_from)

    @property
    def fcm_configured(self) -> bool:
        """True when an FCM service-account (file or JSON) is configured."""
        return bool(self.fcm_credentials_file or self.fcm_credentials_json)

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance.

    Cached via ``lru_cache`` so the ``.env`` file and environment are parsed once
    per process. Tests may call ``get_settings.cache_clear()`` to force a reload.
    """
    return Settings()