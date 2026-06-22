"""Device-token (FCM) schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DeviceTokenCreate(BaseModel):
    """Register or update an FCM device token."""

    fcm_token: str = Field(min_length=10, max_length=4096)
    platform: Literal["android", "ios", "web"]
    device_id: str | None = Field(default=None, max_length=255)
    device_name: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=50)


class DeviceTokenResponse(BaseModel):
    """A registered device token."""

    id: UUID
    fcm_token: str
    platform: str
    device_name: str | None = None
    is_active: bool
    created_at: datetime