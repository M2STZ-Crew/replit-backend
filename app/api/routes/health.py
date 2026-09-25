"""Service index, health, and readiness endpoints.

Public (no authentication), consumed by Docker, nginx, and UptimeRobot (Phase 17).
Readiness now probes the database pool (master context Section 11).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import DatabaseDep
from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.fcm import fcm_status
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
    """Return basic service metadata and useful links. Public."""
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
    """Return liveness and build metadata. Public; no dependency checks."""
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
async def readiness(db: DatabaseDep, response: Response) -> ReadinessResponse:
    """Return readiness to accept traffic, probing the database pool.

    Returns HTTP 200 when ready and HTTP 503 when a dependency is unavailable.
    Public endpoint.
    """
    # Push is reported but never gates readiness: a server that cannot send
    # notifications can still take reports, and should. The check is here so
    # "why are no alerts arriving?" has an answer from outside the server.
    push = "ok" if fcm_status() == "ready" else fcm_status()
    db_ok = db.is_connected and await db.healthcheck()
    if db_ok:
        return ReadinessResponse(
            status="ready", checks={"database": "ok", "push": push}
        )

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    db_status = "unavailable" if not db.is_connected else "error"
    return ReadinessResponse(
        status="not_ready", checks={"database": db_status, "push": push}
    )