"""Application configuration via Pydantic Settings.

Centralizes all runtime configuration for the RepLiT backend. Values are loaded
(in order of precedence) from process environment variables, then a local ``.env``
file. There are NO hardcoded secrets anywhere in the codebase — every tunable or
credential is surfaced here and accessed through :func:`get_settings`.

v8 master context reference: Section 5 (Tech Stack — "Real secrets management via
Pydantic Settings") and Section 13 (Code Style — "No hardcoded secrets; everything
via get_settings()").
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment / ``.env``.

    Field names map case-insensitively to environment variables (e.g. the
    ``app_name`` field reads ``APP_NAME``). Unknown variables in ``.env`` are
    ignored so later-phase variables can coexist before their fields are added.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Core application -----
    environment: Environment = Field(
        default="development",
        description='Deployment environment: "development" | "staging" | "production".',
    )
    app_name: str = Field(default="RepLiT Backend", description="Human-readable app name.")
    app_version: str = Field(default="0.1.0", description="Semantic version of the build.")

    host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    port: int = Field(default=8000, ge=1, le=65535, description="Uvicorn bind port.")

    # ----- Logging -----
    log_level: LogLevel = Field(default="INFO", description="Minimum log level emitted.")
    log_json: bool | None = Field(
        default=None,
        description=(
            "Force JSON logs (True) or pretty console logs (False). When None, JSON is "
            "auto-enabled for any non-development environment."
        ),
    )

    # ----- CORS -----
    # Stored as a raw comma-separated string to avoid pydantic-settings' implicit
    # JSON decoding of list-typed env vars; consume via `cors_origins_list`.
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins.",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Uppercase/trim the log level so values like ``"info"`` are accepted."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

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
        """Resolve the effective log format.

        Honors an explicit ``LOG_JSON`` value; otherwise enables JSON for any
        non-development environment.
        """
        if self.log_json is not None:
            return self.log_json
        return self.environment != "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance.

    Cached via ``lru_cache`` so the ``.env`` file and environment are parsed exactly
    once per process. Tests may call ``get_settings.cache_clear()`` to force a reload
    after mutating environment variables.
    """
    return Settings()  