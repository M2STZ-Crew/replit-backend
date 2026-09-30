"""DeepSeek text-summarization client (Section 3.6).

Writes a concise post-incident report from the structured facts of a closed
incident - the lifecycle, who accepted it, and the team captain's Post-Incident
Report. Text-only. Token usage and an estimated USD cost are returned for
logging into ai_summaries.

DeepSeek's API is OpenAI-compatible:

    POST {base}/chat/completions
    Authorization: Bearer <key>
    {"model": "deepseek-flash", "messages": [...], "max_tokens": N,
     "thinking": {"type": "disabled"}}

Thinking is switched off. It is on by default, and with it on the model spends
output tokens reasoning before it writes - for a four-paragraph summary of
facts it has been handed, that is cost and delay with nothing to show for it,
and it ignores ``temperature``.

The key is read from the setting ``deepseek_summarization`` (the environment
variable of the same name, in either case).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT_S = 60

# USD per token, at DeepSeek's peak-hour rates (off-peak is half). The estimate
# is therefore an upper bound: better to overstate a cost than to understate it.
# (input on a cache miss, input on a cache hit, output)
_PRICES: dict[str, tuple[float, float, float]] = {
    "deepseek-flash": (0.30 / 1_000_000, 0.006 / 1_000_000, 1.20 / 1_000_000),
    "deepseek-v4-pro": (1.32 / 1_000_000, 0.044 / 1_000_000, 3.96 / 1_000_000),
}

_SYSTEM_PROMPT = (
    "You are a fire-incident reporting assistant for the RepLiT coordination "
    "platform in Pasay City, Philippines. Given the structured facts of a closed "
    "incident, write a concise, factual post-incident report for fire coordinators "
    "and the Bureau of Fire Protection. Use plain professional English in 2-4 short "
    "paragraphs. Cover: where it happened, the time of the incident and the time the "
    "fire was out as the team captain recorded them, which agency accepted it and "
    "how soon after it was reported, the response timeline, how many neighbours "
    "corroborated it, the units that went, the driver, the crew and the equipment "
    "taken, and any fire codes activated. If the captain recorded a false alarm, say "
    "so in the first sentence and give the reason. If a fact is missing, leave it "
    "out rather than guessing. Use only the facts provided. Output only the report "
    "text, with no preamble such as 'Here is the report' and no markdown."
)


class DeepSeekNotConfiguredError(AppError):
    """Raised when summarization runs without a DeepSeek API key (HTTP 503)."""

    status_code = 503
    error_code = "ai_not_configured"


@dataclass(frozen=True)
class SummaryResult:
    """A generated summary plus token accounting for ai_summaries."""

    model: str
    summary_text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    cost_usd: float | None
    request_id: str | None


def _cost(model: str, *, prompt: int, cached: int, completion: int) -> float | None:
    """Estimated USD cost, or None for a model whose prices are not listed here."""
    prices = _PRICES.get(model)
    if prices is None:
        return None
    miss, hit, out = prices
    return round(max(prompt - cached, 0) * miss + cached * hit + completion * out, 6)


class DeepSeekClient:
    """Async DeepSeek client for post-incident text summaries."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        s = self._settings
        url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {s.deepseek_summarization}",
            "Content-Type": "application/json",
        }
        if self._http is not None:
            return await self._http.post(url, headers=headers, json=payload, timeout=_TIMEOUT_S)
        # The background summary runs after its request has finished, so there is
        # no shared client to borrow.
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            return await client.post(url, headers=headers, json=payload)

    async def summarize_incident(self, facts_text: str) -> SummaryResult:
        """Summarize an incident's structured facts into a post-incident report."""
        s = self._settings
        if not s.deepseek_configured:
            raise DeepSeekNotConfiguredError(
                "AI summarization is not configured (set deepseek_summarization)."
            )

        payload = {
            "model": s.deepseek_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": facts_text},
            ],
            "max_tokens": s.deepseek_max_tokens,
            "temperature": 0.2,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        try:
            response = await self._post(payload)
        except httpx.HTTPError as exc:
            log.error("deepseek_request_failed", error=str(exc))
            raise ExternalServiceError("AI summarization request failed.") from exc

        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            # 401 wrong key, 402 no balance, 429 rate limit, 5xx their side: the
            # log says which; the caller gets one plain failure.
            error = body.get("error")
            detail = error.get("message") if isinstance(error, dict) else None
            log.error(
                "deepseek_request_failed",
                status_code=response.status_code,
                detail=str(detail or "")[:300],
            )
            raise ExternalServiceError("AI summarization request failed.")

        choices = body.get("choices") or []
        choice = choices[0] if choices else {}
        finish = choice.get("finish_reason")
        usage = body.get("usage") or {}
        completion_tokens = int(usage.get("completion_tokens") or 0)

        # A report cut off at max_tokens reads as complete when stored, so it is
        # refused here rather than written; the caller can raise
        # DEEPSEEK_MAX_TOKENS and try again. A filtered answer has no report in it.
        if finish == "length":
            log.error(
                "deepseek_summary_truncated",
                max_tokens=s.deepseek_max_tokens,
                output_tokens=completion_tokens,
            )
            raise ExternalServiceError(
                "The AI summary was cut off before it finished. Raise "
                "DEEPSEEK_MAX_TOKENS and generate it again."
            )
        if finish == "content_filter":
            log.error("deepseek_summary_refused")
            raise ExternalServiceError("The AI declined to summarize this incident.")
        if finish != "stop":
            log.error("deepseek_summary_incomplete", finish_reason=str(finish))
            raise ExternalServiceError("The AI did not finish the summary. Generate it again.")

        summary_text = str((choice.get("message") or {}).get("content") or "").strip()
        if not summary_text:
            raise ExternalServiceError("AI returned an empty summary.")

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        cached = int(usage.get("prompt_cache_hit_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
        cost_usd = _cost(
            s.deepseek_model, prompt=prompt_tokens, cached=cached, completion=completion_tokens
        )

        log.info(
            "deepseek_summary_generated",
            model=s.deepseek_model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cached_tokens=cached,
            cost_usd=cost_usd,
        )
        return SummaryResult(
            model=s.deepseek_model,
            summary_text=summary_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            request_id=body.get("id"),
        )
