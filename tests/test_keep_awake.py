"""The free Render instance keeps itself awake (hermetic, 8 Nov 2026).

On 7 and 8 November the sleeping service stopped waking; only a manual deploy
brought it back. What these pin:
- the address is this service's own public /health: KEEP_AWAKE_URL, or the
  RENDER_EXTERNAL_URL Render sets; nowhere else (a laptop, the tests) is
  there one, and nothing runs;
- the job knocks every KEEP_AWAKE_MINUTES (10, under Render's 15), once at a
  time, and 0 turns it off;
- a knock never raises: an answer that is not a 200, or none, is logged.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from app.core.config import get_settings
from app.workers import keep_awake
from app.workers.keep_awake import (
    keep_awake_url,
    knock,
    shutdown_keep_awake_scheduler,
    start_keep_awake_scheduler,
)

RENDER = "https://replit-backend-2li4.onrender.com"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    s = get_settings()
    monkeypatch.setattr(s, "keep_awake_minutes", 10)
    monkeypatch.setattr(s, "keep_awake_url", "")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    shutdown_keep_awake_scheduler()
    yield
    shutdown_keep_awake_scheduler()


# --------------------------------------------------------------------------- #
# Where to knock
# --------------------------------------------------------------------------- #
def test_off_render_there_is_no_address() -> None:
    assert keep_awake_url() is None


def test_on_render_it_is_the_service_s_own_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_EXTERNAL_URL", RENDER + "/")
    assert keep_awake_url() == RENDER + "/health"


def test_keep_awake_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_EXTERNAL_URL", RENDER)
    monkeypatch.setattr(get_settings(), "keep_awake_url", "https://api.example.com/health")
    assert keep_awake_url() == "https://api.example.com/health"


# --------------------------------------------------------------------------- #
# A knock
# --------------------------------------------------------------------------- #
def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_a_knock_asks_for_health_once() -> None:
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async with _client(httpx.MockTransport(answer)) as client:
        assert await knock(RENDER + "/health", client) is True
    assert [str(r.url) for r in asked] == [RENDER + "/health"]
    assert asked[0].headers["user-agent"] == "replit-backend keep-awake"


@pytest.mark.parametrize(
    "answer",
    [
        lambda _r: httpx.Response(503),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
    ],
    ids=["503", "no connection", "too slow"],
)
async def test_a_knock_that_fails_says_so_and_never_raises(answer: object) -> None:
    async with _client(httpx.MockTransport(answer)) as client:  # type: ignore[arg-type]
        assert await knock(RENDER + "/health", client) is False


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #
async def test_on_render_it_knocks_every_ten_minutes_once_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER_EXTERNAL_URL", RENDER)
    start_keep_awake_scheduler()
    start_keep_awake_scheduler()  # idempotent

    scheduler = keep_awake._scheduler
    assert scheduler is not None
    job = scheduler.get_job("keep_awake")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 600
    assert job.args == (RENDER + "/health",)
    assert job.max_instances == 1

    shutdown_keep_awake_scheduler()
    assert keep_awake._scheduler is None


async def test_nothing_runs_off_render_or_when_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_keep_awake_scheduler()
    assert keep_awake._scheduler is None

    monkeypatch.setenv("RENDER_EXTERNAL_URL", RENDER)
    monkeypatch.setattr(get_settings(), "keep_awake_minutes", 0)
    start_keep_awake_scheduler()
    assert keep_awake._scheduler is None


def test_ten_minutes_is_under_render_s_fifteen() -> None:
    field = type(get_settings()).model_fields["keep_awake_minutes"]
    assert field.default == 10
    assert any(getattr(m, "le", None) == 14 for m in field.metadata)
