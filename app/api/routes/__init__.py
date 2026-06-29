"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    admin,
    affiliates,
    ai,
    alarm_requests,
    areas,
    audit,
    auth,
    devices,
    equipment,
    fire_codes,
    health,
    hydrant_ops,
    incident_reports,
    incidents,
    map_layer_requests,
    map_layers,
    map_layers_admin,
    notifications,
    organizations,
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
api_router.include_router(organizations.router)
api_router.include_router(map_layers.router)
api_router.include_router(map_layers_admin.router)
api_router.include_router(hydrant_ops.router)
api_router.include_router(map_layer_requests.router)
api_router.include_router(fire_codes.router)
api_router.include_router(alarm_requests.router)
api_router.include_router(audit.router)
api_router.include_router(incident_reports.router)