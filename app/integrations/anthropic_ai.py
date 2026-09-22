"""Anthropic Claude (Haiku) text-summarization client (Section 3.6).

Writes a concise post-incident report from the structured facts of a closed
incident — the lifecycle, who accepted it, and the team captain's Post-Incident
Report (v11 Section 2.5.3). Text-only (no vision). Token usage and an estimated
USD cost are returned for logging into ai_summaries.

The system prompt is sent without a cache breakpoint. Haiku 4.5 only caches a
prefix of 4,096 tokens or more, and this prompt is about 200: a marker here would
silently never cache while the cost accounting assumed it might. If the prompt
ever grows past the minimum — or the model changes to one with a lower one — add
``cache_control`` back; the cost formula below already prices cache reads and
writes, so it stays correct either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import APIError, AsyncAnthropic

from app.core.config import get_settings
from app.core.exceptions import AppError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)

# Claude Haiku 4.5 pricing (USD per token). Cache writes ~1.25x input; reads ~0.1x.
_INPUT_PER_TOKEN = 1.00 / 1_000_000
_OUTPUT_PER_TOKEN = 5.00 / 1_000_000
_CACHE_WRITE_PER_TOKEN = 1.25 / 1_000_000
_CACHE_READ_PER_TOKEN = 0.10 / 1_000_000

_SYSTEM_PROMPT = (
    "You are a fire-incident reporting assistant for the RepLiT coordination "
    "platform in Pasay City, Philippines. Given the structured facts of a closed "
    "incident, write a concise, factual post-incident report for fire coordinators "
    "and the Bureau of Fire Protection. Use plain professional English in 2-4 short "
    "paragraphs. Cover: where and when it happened, which agency accepted it and how "
    "soon after it was reported, the response timeline through to fire out, how many "
    "neighbours corroborated it, the unit, crew and equipment the team captain "
    "recorded, and any fire codes activated. If the captain recorded a false alarm, "
    "say so in the first sentence and give their explanation. If a fact is missing, "
    "leave it out rather than guessing. Use only the facts provided. Output only the "
    "report text, with no preamble such as 'Here is the report'."
)


class AnthropicNotConfiguredError(AppError):
    """Raised when summarization runs without an Anthropic API key (HTTP 503)."""

    status_code = 503
    error_code = "anthropic_not_configured"


@dataclass(frozen=True)
class SummaryResult:
    """A generated summary plus token accounting for ai_summaries."""

    model: str
    summary_text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_usd: float
    request_id: str | None


class AnthropicClient:
    """Async Claude Haiku client for post-incident text summaries."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def summarize_incident(self, facts_text: str) -> SummaryResult:
        """Summarize an incident's structured facts into a post-incident report."""
        s = self._settings
        if not s.anthropic_configured:
            raise AnthropicNotConfiguredError(
                "AI summarization is not configured (set ANTHROPIC_API_KEY in .env)."
            )

        try:
            async with AsyncAnthropic(api_key=s.anthropic_api_key) as client:
                message = await client.messages.create(
                    model=s.anthropic_model,
                    max_tokens=s.anthropic_max_tokens,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": facts_text}],
                )
        except APIError as exc:
            log.error("anthropic_request_failed", error=str(exc))
            raise ExternalServiceError("AI summarization request failed.") from exc

        # A report cut off at max_tokens reads as complete when stored, so it is
        # refused here rather than written; the caller can raise
        # ANTHROPIC_MAX_TOKENS and try again. A refusal likewise has no report in it.
        if message.stop_reason == "max_tokens":
            log.error(
                "anthropic_summary_truncated",
                max_tokens=s.anthropic_max_tokens,
                output_tokens=message.usage.output_tokens,
            )
            raise ExternalServiceError(
                "The AI summary was cut off before it finished. Raise "
                "ANTHROPIC_MAX_TOKENS and generate it again."
            )
        if message.stop_reason == "refusal":
            log.error("anthropic_summary_refused")
            raise ExternalServiceError("The AI declined to summarize this incident.")

        summary_text = "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()
        if not summary_text:
            raise ExternalServiceError("AI returned an empty summary.")

        usage = message.usage
        prompt_tokens = usage.input_tokens
        completion_tokens = usage.output_tokens
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        total_tokens = prompt_tokens + completion_tokens + cache_read + cache_write
        cost_usd = round(
            prompt_tokens * _INPUT_PER_TOKEN
            + completion_tokens * _OUTPUT_PER_TOKEN
            + cache_write * _CACHE_WRITE_PER_TOKEN
            + cache_read * _CACHE_READ_PER_TOKEN,
            6,
        )

        log.info(
            "anthropic_summary_generated",
            model=s.anthropic_model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cached_tokens=cache_read,
            cost_usd=cost_usd,
        )
        return SummaryResult(
            model=s.anthropic_model,
            summary_text=summary_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cache_read,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            request_id=message._request_id,
        )
