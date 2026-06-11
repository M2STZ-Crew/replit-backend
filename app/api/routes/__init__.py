"""Aggregate API router.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import admin, auth, health, verification

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(verification.router)
api_router.include_router(admin.router)