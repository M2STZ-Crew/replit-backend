"""Shared Pydantic schemas used across multiple routers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error envelope returned by all global exception handlers.

    v8 master context Section 13 (Code Style): every response body is a Pydantic
    model — including errors — so clients can rely on a single, stable error shape.
    """

    error: str = Field(description="Stable machine-readable error code (snake_case).")
    message: str = Field(description="Human-readable description of the error.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured context (e.g. field-level validation errors).",
    )
    request_id: str | None = Field(
        default=None,
        description="Correlation id of the originating request, when available.",
    )