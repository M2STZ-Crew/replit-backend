"""AI summary (Claude Haiku) schemas (Phase 11, Section 3.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AISummaryResponse(BaseModel):
    """A stored post-incident AI summary with token + cost accounting."""

    id: UUID
    area_id: UUID
    model: str
    summary_text: str
    structured_report: dict[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    anthropic_request_id: str | None = None
    generated_at: datetime