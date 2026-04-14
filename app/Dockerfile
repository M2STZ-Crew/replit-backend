"""
main.py – FastAPI application entry point.
Configures middleware, CORS, routers, and startup events.
"""

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.api.v1.endpoints.health import router as health_router
# Future routers imported here as phases are completed:
# from app.api.v1.endpoints.auth import router as auth_router
# from app.api.v1.endpoints.incidents import router as incidents_router

settings = get_settings()

# ── Sentry Error Monitoring (no-op if DSN is empty) ──────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=0.2,  # Capture 20% of transactions
    )

# ── Rate Limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App Instance ──────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Real-time Emergency Incident Reporting & Dispatch API",
    docs_url="/docs" if settings.DEBUG else None,   # Hide docs in production
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ── Middleware: Rate Limiting ─────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware: CORS ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(health_router, prefix="/api/v1")
# app.include_router(auth_router, prefix="/api/v1")     # Phase 4
# app.include_router(incidents_router, prefix="/api/v1") # Phase 5


@app.on_event("startup")
async def on_startup():
    """
    Runs on application startup.
    Good place for DB connection pool warmup, cache initialization, etc.
    """
    print(f"🚀 {settings.APP_NAME} starting in {settings.APP_ENV} mode")


@app.on_event("shutdown")
async def on_shutdown():
    """Cleanup on graceful shutdown."""
    print("🛑 RepLit API shutting down")