"""Service index, health, and readiness endpoints.

These are public (no authentication) and consumed by the Docker health check, the
nginx upstream probe, and UptimeRobot (configured in Phase 17). v8 master context
Section 11 (Phase 1 deliverables) — health check endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.health import HealthResponse, ReadinessResponse, ServiceInfoResponse

log = get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=ServiceInfoResponse,
    status_code=status.HTTP_200_OK,
    tags=["meta"],
    summary="Service index",
)
async def root() -> ServiceInfoResponse:
    """Return basic service metadata and useful links.

    Public endpoint hit when browsing the API base URL.
    """
    settings = get_settings()
    return ServiceInfoResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        docs_url="/docs",
        health_url="/health",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["health"],
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    """Return liveness and build metadata.

    Public endpoint. Confirms the FastAPI process is running and able to serve
    requests; performs no dependency checks.
    """
    settings = get_settings()
    return HealthResponse(
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    tags=["health"],
    summary="Readiness probe",
)
async def readiness() -> ReadinessResponse:
    """Return readiness to accept traffic.

    Public endpoint. In Phase 1 there are no external dependencies, so this always
    reports ``ready``. Later phases add database/Redis/external-service checks and
    may return ``not_ready`` with details.
    """
    return ReadinessResponse(status="ready", checks={})