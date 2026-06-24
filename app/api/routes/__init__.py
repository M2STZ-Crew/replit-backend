"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    admin,
    affiliates,
    ai,
    areas,
    auth,
    devices,
    equipment,
    health,
    hydrant_ops,
    incidents,
    map_layer_requests,
    map_layers,
    map_layers_admin,
    notifications,
    reports,
    verification,
    ws,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(verification.router)
api_router.include_router(admin.router)
api_router.include_router(devices.router)
api_router.include_router(reports.router)
api_router.include_router(areas.router)
api_router.include_router(notifications.router)
api_router.include_router(incidents.router)
api_router.include_router(ws.router)
api_router.include_router(ai.router)
api_router.include_router(equipment.router)
api_router.include_router(affiliates.router)
api_router.include_router(map_layers.router)
api_router.include_router(map_layers_admin.router)
api_router.include_router(hydrant_ops.router)
api_router.include_router(map_layer_requests.router)