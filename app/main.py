"""RepLiT backend application entrypoint.

Builds and configures the FastAPI application: logging, shared resources (HTTP
client + database pool), CORS, request-correlation middleware, global exception
handlers, and the mounted API router. Import target for Uvicorn as ``app.main:app``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import database
from app.integrations.fcm import init_fcm, shutdown_fcm
from app.services.audit import maybe_record_request_audit
from app.workers.neighborhood import (
    shutdown_neighborhood_scheduler,
    start_neighborhood_scheduler,
)

log = get_logger(__name__)

# Probe endpoints whose per-request logs are demoted to DEBUG to avoid log spam.
_QUIET_PATHS = {"/health", "/health/ready"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging, open shared resources, log lifecycle."""
    configure_logging()
    settings = get_settings()

    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    await database.connect()
    init_fcm()
    start_neighborhood_scheduler()

    log.info(
        "application_startup",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database_connected=database.is_connected,
    )
    yield

    shutdown_neighborhood_scheduler()
    shutdown_fcm()
    await database.disconnect()
    await app.state.http_client.aclose()
    log.info("application_shutdown")


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Assign/propagate a request id, bind log context, and time the request."""
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        emit = log.debug if request.url.path in _QUIET_PATHS else log.info
        start = time.perf_counter()
        emit("request_started")

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.exception("request_failed", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        emit("request_completed", status_code=response.status_code, duration_ms=duration_ms)
        response.headers["X-Request-ID"] = request_id
        await maybe_record_request_audit(request, response)
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_settings.host,
        port=_settings.port,
        reload=_settings.is_development,
        access_log=False,
    )