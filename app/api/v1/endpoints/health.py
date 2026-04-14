# app/schemas/incident.py
"""
incident.py – Request and response schemas for incident endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.enums import IncidentStatus, IncidentSeverity
import uuid


class LocationSchema(BaseModel):
    """GPS coordinates."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class CreateReportRequest(BaseModel):
    """
    Payload submitted by a citizen when reporting an emergency.
    Media is uploaded separately via /upload endpoint.
    """
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    description: Optional[str] = Field(None, max_length=1000)


class IncidentResponse(BaseModel):
    """Full incident detail returned to clients."""
    id: uuid.UUID
    title: Optional[str]
    description: Optional[str]
    ai_summary: Optional[str]
    status: IncidentStatus
    severity: IncidentSeverity
    report_count: int
    address: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime
    updated_at: datetime


class UpdateIncidentStatusRequest(BaseModel):
    """Used by dispatcher/admin to change incident status."""
    status: IncidentStatus
    note: Optional[str] = None