"""Application configuration via Pydantic Settings.

Single source of truth for all runtime configuration and secrets, loaded from
environment variables then a local ``.env`` file, accessed via :func:`get_settings`.
No hardcoded secrets anywhere (master context Section 5, Section 13).

Optional integration sections (Supabase, database, Semaphore) default to empty so the
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
    app_version: str = Field(default="1.12.1", description="Semantic version of the build.")
    host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    port: int = Field(default=8000, ge=1, le=65535, description="Uvicorn bind port.")

    log_level: LogLevel = Field(default="INFO", description="Minimum log level emitted.")
    log_json: bool | None = Field(
        default=None,
        description="Force JSON logs; None auto-enables JSON for non-development.",
    )
    cors_origins: str = Field(
        # 5173: Admin Console (admin-web). 5174: Observer Console (observer-web).
        default="http://localhost:5173,http://localhost:5174,http://localhost:3000",
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

    # ----- Semaphore SMS (phone OTP, +40%) -----
    # Semaphore only sends: it does not check codes the way Twilio Verify did, so
    # the backend generates, stores (as an HMAC) and checks every code itself.
    semaphore_api_key: str = Field(default="", description="Semaphore API key (secret).")
    semaphore_base_url: str = Field(
        default="https://api.semaphore.co/api/v4", description="Semaphore API root."
    )
    semaphore_sender_name: str = Field(
        default="",
        description="Approved sender name. Empty uses the account's default sender.",
    )
    phone_otp_length: int = Field(default=6, ge=4, le=8, description="Digits in a phone code.")
    phone_otp_ttl_seconds: int = Field(
        default=300, ge=60, le=1800, description="How long a phone code stays valid."
    )
    phone_otp_max_attempts: int = Field(
        default=5, ge=1, le=10,
        description="Wrong guesses allowed before a code is thrown away.",
    )
    # Each code costs two Semaphore credits and the OTP route has no rate limit
    # of its own, so these limits are what stands between a script and the
    # credit balance. The per-number cap spans accounts: making ten accounts does
    # not buy ten times the texts to one victim's phone.
    phone_otp_resend_cooldown_seconds: int = Field(
        default=60, ge=0, le=3600, description="Minimum wait between two codes to one account."
    )
    phone_otp_daily_limit_per_user: int = Field(
        default=5, ge=1, le=50, description="Codes one account may request in 24 hours."
    )
    phone_otp_daily_limit_per_number: int = Field(
        default=5, ge=1, le=50,
        description="Codes one phone number may receive in 24 hours, across all accounts.",
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
    # 2525, not 587: Render's free web services block outbound SMTP on 25, 465
    # and 587, so on 587 every email from the deployed server times out. Brevo's
    # relay takes the same login on 2525.
    brevo_smtp_port: int = Field(default=2525, ge=1, le=65535, description="Brevo SMTP port.")
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

    # ----- Citizen phone gate -----
    # A citizen account must verify a Philippine mobile number before it can use
    # the app. A switch rather than a constant because the gate stands on SMS
    # delivery: if Semaphore stops delivering, or the credit runs out, every
    # unverified citizen is locked out, and turning the gate off from the Render
    # dashboard is the recovery that needs no deploy. Staff are never gated.
    require_citizen_phone_verification: bool = Field(
        default=True,
        description="Refuse citizen API access until the account's phone is verified.",
    )

    # ----- Live responder tracking -----
    # Arrival is measured against the Area's centroid, which is the average of
    # the citizens' own report positions — itself up to tens of metres from the
    # fire. Too tight and a truck parked outside never counts as arrived; too
    # loose and it arrives a street early. Tune it during testing.
    arrival_radius_meters: float = Field(
        default=100.0, ge=10, le=500,
        description="A responder this close to the Area centroid is on scene.",
    )
    arrival_consecutive_fixes: int = Field(
        default=2, ge=1, le=10,
        description="Fixes in a row inside the radius before arrival is declared.",
    )
    responder_fix_max_age_seconds: int = Field(
        default=120, ge=10, le=3600,
        description="A fix older than this is kept for history but cannot move status.",
    )
    tracking_stale_after_seconds: int = Field(
        default=60, ge=5, le=3600,
        description="A responder position older than this is shown to citizens as stale.",
    )

 # ----- Anthropic (Claude Haiku) AI summarization (Phase 11, Section 3.6) -----
    anthropic_api_key: str = Field(
        default="", description="Anthropic API key (Claude); server-only."
    )
    anthropic_model: str = Field(
        default="claude-haiku-4-5",
        description="Claude model id for post-incident summaries (text-only).",
    )
    anthropic_max_tokens: int = Field(
        default=1024, ge=1, le=8192, description="Max output tokens per summary."
    )


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
    def semaphore_configured(self) -> bool:
        """True when a Semaphore API key is present."""
        return bool(self.semaphore_api_key)
    
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
    
    @property
    def anthropic_configured(self) -> bool:
        """True when an Anthropic API key is present."""
        return bool(self.anthropic_api_key)

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance.

    Cached via ``lru_cache`` so the ``.env`` file and environment are parsed once
    per process. Tests may call ``get_settings.cache_clear()`` to force a reload.
    """
    return Settings()

    