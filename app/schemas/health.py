"""Pydantic schemas for the service index, health, and readiness endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ServiceInfoResponse(BaseModel):
    """Service index payload returned at the API root (``GET /``)."""

    service: str = Field(description="Configured application name.")
    version: str = Field(description="Running build version.")
    environment: str = Field(description="Active deployment environment.")
    docs_url: str = Field(description="Path to the interactive Swagger UI.")
    health_url: str = Field(description="Path to the liveness probe.")


class HealthResponse(BaseModel):
    """Liveness probe payload — confirms the process is up and serving."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok' when serving.")
    app_name: str = Field(description="Configured application name.")
    version: str = Field(description="Running build version.")
    environment: str = Field(description="Active deployment environment.")


class ReadinessResponse(BaseModel):
    """Readiness probe payload — confirms the app can accept traffic.

    In Phase 1 there are no external dependencies, so readiness mirrors liveness.
    Later phases extend ``checks`` with database / Redis / external-service probes
    and may report ``not_ready``.
    """

    status: Literal["ready", "not_ready"] = Field(description="Overall readiness state.")
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency results (name -> 'ok' | reason).",
    )