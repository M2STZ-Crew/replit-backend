"""Application error types and global exception handlers.

Defines a single base :class:`AppError` (plus a focused set of HTTP-mapped
subclasses) and registers process-wide exception handlers on the FastAPI app, so
every error — expected or not — returns a consistent JSON envelope and is logged
with structured context.

Per the v8 code-style rules (master context Section 13): known exceptions are
caught explicitly and raised as :class:`AppError` subclasses; unknown exceptions
propagate to the catch-all handler here, which logs them and returns a safe 500
without leaking internals.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.schemas.common import ErrorResponse

log = get_logger(__name__)


class AppError(Exception):
    """Base class for all expected, handled application errors.

    Attributes:
        status_code: HTTP status code to return.
        error_code: Stable machine-readable identifier (snake_case), e.g. "not_found".
        message: Human-readable explanation safe to return to clients.
        details: Optional structured context (field errors, identifiers, etc.).
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        self.details = details
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class BadRequestError(AppError):
    """The request was malformed or semantically invalid (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "bad_request"


class UnauthorizedError(AppError):
    """Authentication is missing or invalid (HTTP 401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class ForbiddenError(AppError):
    """Authenticated but not permitted (HTTP 403) — used by RBAC enforcement."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"


class NotFoundError(AppError):
    """The requested resource does not exist (HTTP 404)."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current resource state (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class ExternalServiceError(AppError):
    """A required third-party service failed or was unavailable (HTTP 502).

    Used by later-phase integrations (Didit.me, Twilio, Brevo, FCM, Anthropic).
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_service_error"


def _request_id(request: Request) -> str | None:
    """Best-effort extraction of the correlation request id set by middleware."""
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else None


def _json_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a JSONResponse from the standard :class:`ErrorResponse` envelope."""
    payload = ErrorResponse(
        error=error_code,
        message=message,
        details=details,
        request_id=request_id,
    )
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 5xx are unexpected server-side; 4xx are client errors.
        if exc.status_code >= 500:
            log.error(
                "app_error",
                error_code=exc.error_code,
                status_code=exc.status_code,
                message=exc.message,
                details=exc.details,
            )
        else:
            log.warning(
                "app_error",
                error_code=exc.error_code,
                status_code=exc.status_code,
                message=exc.message,
                details=exc.details,
            )
        return _json_error(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            request_id=_request_id(request),
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        log.warning("request_validation_error", error_count=len(errors))
        return _json_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="validation_error",
            message="Request validation failed.",
            request_id=_request_id(request),
            details={"errors": jsonable_encoder(errors)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error."
        log.warning("http_exception", status_code=exc.status_code, detail=detail)
        return _json_error(
            status_code=exc.status_code,
            error_code=f"http_{exc.status_code}",
            message=detail,
            request_id=_request_id(request),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback is logged server-side; the client gets a safe generic message.
        log.exception("unhandled_exception", exc_type=type(exc).__name__)
        return _json_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="internal_error",
            message="An unexpected error occurred.",
            request_id=_request_id(request),
        )