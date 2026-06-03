"""Aggregate API router.

Combines all route modules into a single router that ``app.main`` mounts on the
application. Later phases register their routers here (auth, reports, areas,
notifications, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router)