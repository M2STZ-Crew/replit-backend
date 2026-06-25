"""Audit log schemas (Phase 14, Section 7 #20)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    """An audit_logs row."""

    id: UUID
    actor_user_id: UUID | None = None
    actor_role: str | None = None
    actor_agency: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    area_id: UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime