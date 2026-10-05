"""AI summary (DeepSeek) schemas (Phase 11, Section 3.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
    provider_request_id: str | None = None
    generated_at: datetime


class SummarizedIncident(BaseModel):
    """One row of a coordinator's AI summaries list (v1.12.5)."""

    area_id: UUID
    designation: str
    status: str
    reported_at: datetime | None = None
    closed_at: datetime | None = None
    reports_filed: int = Field(description="Post-Incident Reports filed, one per team.")
    teams: list[str] = Field(description="The teams that filed, in filing order.")
    last_filed_at: datetime
    state: Literal["ready", "writing", "unavailable"] = Field(
        description=(
            "ready: the summary covers every team's report. writing: one is owed and "
            "the server is writing it; refresh shortly. unavailable: one is owed and "
            "the server has no AI key. A summary from before the newest report is "
            "still returned while its replacement is written."
        )
    )
    summary_id: UUID | None = None
    summary_text: str | None = None
    model: str | None = None
    generated_at: datetime | None = None


class ReportLinkResponse(BaseModel):
    """A short-lived link to download an incident's PDF in a browser (v1.12.5)."""

    path: str = Field(description="Relative to the API's base URL; carries its own signature.")
    expires_at: datetime
