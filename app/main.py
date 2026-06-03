"""RepLiT backend application entrypoint.

Builds and configures the FastAPI application: logging, CORS, request-correlation
middleware, global exception handlers, and the mounted API router. Import target for
Uvicorn as ``app.main:app``.

v8 master context references: Section 8 (Architecture — FastAPI server), Section 13
(Code Style — structured logging, correlation IDs, no raw dicts in/out of endpoints).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

# Probe endpoints whose per-request logs are demoted to DEBUG to avoid log spam.
_QUIET_PATHS = {"/health", "/health/ready"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging on startup, log lifecycle events."""
    configure_logging()
    settings = get_settings()
    log.info(
        "application_startup",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
    yield
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
            # Re-raise so the registered global handlers build the response; the
            # bound request_id remains in context for that handler's logs.
            log.exception("request_failed", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        emit("request_completed", status_code=response.status_code, duration_ms=duration_ms)
        response.headers["X-Request-ID"] = request_id
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
        access_log=False,  # request logging is handled by request_context_middleware
    )