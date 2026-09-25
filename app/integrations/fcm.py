"""Firebase Cloud Messaging: app init + generic push service.

The Firebase Admin SDK is synchronous, so sends run in a worker thread. The push
service is FCM-only (no DB): callers fetch device tokens / choose topics and pass
them in. Used by Phase 8 (neighborhood alerts) and Phase 9 (lifecycle pushes).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_FCM_APP_NAME = "replit-fcm"
_fcm_app: firebase_admin.App | None = None

FcmState = Literal["unconfigured", "failed", "ready"]

# Why push is or is not working, kept so a caller can say so. Without it, a
# server with no credentials and a server whose credentials would not load both
# answered a test push with "sent to 0 devices; 0 failed" — a success message
# for a push that never left.
_fcm_state: FcmState = "unconfigured"

# The repository root, so a relative credentials path means the same file
# whichever directory the server was started from.
_ROOT = Path(__file__).resolve().parents[2]


def fcm_status() -> FcmState:
    """'ready' when FCM initialised; otherwise why it did not."""
    return _fcm_state


def _credentials_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else _ROOT / path


def init_fcm() -> None:
    """Initialize the Firebase app from config. No-op if unconfigured or already done."""
    global _fcm_app, _fcm_state
    if _fcm_app is not None:
        return
    settings = get_settings()
    if not settings.fcm_configured:
        _fcm_state = "unconfigured"
        log.warning("fcm_not_configured", detail="FCM credentials missing; push disabled")
        return
    try:
        if settings.fcm_credentials_json:
            cred = credentials.Certificate(json.loads(settings.fcm_credentials_json))
        else:
            path = _credentials_path(settings.fcm_credentials_file)
            if not path.is_file():
                # The usual way this goes wrong on a host: the variable was
                # copied from a laptop's .env, and the file it names is
                # gitignored, so it was never deployed.
                raise FileNotFoundError(
                    f"FCM_CREDENTIALS_FILE names {path.name}, which is not on this "
                    "server. On a host, set FCM_CREDENTIALS_JSON to the file's "
                    "contents instead."
                )
            cred = credentials.Certificate(str(path))
        _fcm_app = firebase_admin.initialize_app(cred, name=_FCM_APP_NAME)
        _fcm_state = "ready"
        log.info("fcm_initialized")
    except Exception:
        _fcm_app = None
        _fcm_state = "failed"
        log.error("fcm_init_failed", exc_info=True)


def shutdown_fcm() -> None:
    """Delete the Firebase app on shutdown (idempotent)."""
    global _fcm_app, _fcm_state
    if _fcm_app is not None:
        try:
            firebase_admin.delete_app(_fcm_app)
        except Exception:
            log.warning("fcm_shutdown_failed", exc_info=True)
        _fcm_app = None
        _fcm_state = "unconfigured"


@dataclass
class PushResult:
    """Outcome of a multicast push."""

    success_count: int = 0
    failure_count: int = 0
    invalid_tokens: list[str] = field(default_factory=list)


class PushService:
    """Async wrapper over FCM send operations (no DB access)."""

    @property
    def is_available(self) -> bool:
        """True when the Firebase app initialized successfully."""
        return _fcm_app is not None

    async def send_to_tokens(
        self,
        *,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> PushResult:
        """Send a notification to many device tokens; report invalid ones for cleanup."""
        if not tokens or _fcm_app is None:
            return PushResult()

        def _send() -> PushResult:
            message = messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                # High priority so the alert is delivered promptly and shown even
                # when the app is backgrounded or terminated (FCM default channel).
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(default_sound=True),
                ),
            )
            batch = messaging.send_each_for_multicast(message, app=_fcm_app)
            invalid: list[str] = []
            for token, resp in zip(tokens, batch.responses, strict=False):
                if not resp.success and isinstance(
                    resp.exception,
                    (messaging.UnregisteredError, messaging.SenderIdMismatchError),
                ):
                    invalid.append(token)
            return PushResult(
                success_count=batch.success_count,
                failure_count=batch.failure_count,
                invalid_tokens=invalid,
            )

        try:
            return await asyncio.to_thread(_send)
        except Exception:
            log.error("fcm_multicast_failed", exc_info=True)
            return PushResult(failure_count=len(tokens))

    async def send_to_topic(
        self,
        *,
        topic: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> str | None:
        """Send a notification to an FCM topic; return the message id or None."""
        if _fcm_app is None:
            return None

        def _send() -> str:
            message = messaging.Message(
                topic=topic,
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
            )
            return str(messaging.send(message, app=_fcm_app))

        try:
            return await asyncio.to_thread(_send)
        except Exception:
            log.error("fcm_topic_failed", topic=topic, exc_info=True)
            return None