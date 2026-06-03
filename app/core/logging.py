"""Structured logging configuration (structlog).

Emits JSON logs in non-development environments and human-friendly colored console
logs in development. Standard-library logging (including Uvicorn's loggers) is routed
through structlog so ALL log output shares one consistent format and renderer.

Context variables bound via ``structlog.contextvars.bind_contextvars`` (e.g.
``request_id``, ``user_id``, ``incident_id``, ``area_id``) are merged into every log
line emitted within that context — satisfying the v8 requirement to bind correlation
IDs where applicable (master context Section 13, Code Style).
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging() -> None:
    """Configure structlog + stdlib logging for the whole process.

    Idempotent: safe to call once on application startup (and again in tests). Reads
    the active settings to choose the level and renderer (JSON vs. console). Existing
    handlers are cleared first so repeated calls never duplicate log output.
    """
    # Imported lazily to avoid any import-time coupling/cycles with config.
    from app.core.config import get_settings

    settings = get_settings()
    log_level = getattr(logging, settings.log_level, logging.INFO)

    # Processors shared by both structlog-native records and foreign (stdlib) records,
    # applied BEFORE the final renderer. Order matters.
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Final renderer: structured JSON for non-dev, colored console for dev.
    renderer: structlog.typing.Processor
    if settings.use_json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog: native loggers run the shared processors, then hand the
    # event dict to stdlib via ProcessorFormatter. Level filtering is delegated to
    # stdlib (handler/logger levels set below).
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # One stdlib formatter renders BOTH structlog-originated records and plain stdlib
    # records (e.g. Uvicorn) using the shared processors + chosen renderer.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Route Uvicorn's loggers through the root handler instead of their private ones.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
        uv_logger.setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling module.

    Returns:
        A ``structlog.stdlib.BoundLogger`` ready for structured logging, e.g.
        ``log.info("report_submitted", report_id=rid)``.
    """
    return structlog.stdlib.get_logger(name)