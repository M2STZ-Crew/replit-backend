"""Firebase Cloud Messaging: app init + generic push service.

The Firebase Admin SDK is synchronous, so sends run in a worker thread. The push
service is FCM-only (no DB): callers fetch device tokens / choose topics and pass
them in. Used by Phase 8 (neighborhood alerts) and Phase 9 (lifecycle pushes).

v1.12.6: two Android notification channels, created by the app
(MainActivity.kt). A push that says there is a fire — a new incident for
staff, a neighbour's first alert, an alarm escalation — goes to
``fire_alerts``, which rings with the app's fire alarm sound; everything else
goes to ``updates`` with the phone's own tone. And when FCM will not start,
the server now says why, in words safe to show anyone (no credential content).
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

# The channels the app creates (android/app/src/main/kotlin/.../MainActivity.kt)
# and the sound file the fire channel plays (res/raw/fire_alarm.wav). Android
# picks the sound from the channel; ``sound`` is for phones before Android 8.
FIRE_CHANNEL = "fire_alerts"
UPDATES_CHANNEL = "updates"
FIRE_SOUND = "fire_alarm"

# Why push is or is not working, kept so a caller can say so. Without it, a
# server with no credentials and a server whose credentials would not load both
# answered a test push with "sent to 0 devices; 0 failed" — a success message
# for a push that never left.
_fcm_state: FcmState = "unconfigured"

# Why it failed, in a sentence an administrator can act on. Never the error
# text itself: a credentials parser's message can quote the credentials.
_fcm_reason: str | None = None

# The repository root, so a relative credentials path means the same file
# whichever directory the server was started from.
_ROOT = Path(__file__).resolve().parents[2]


def fcm_status() -> FcmState:
    """'ready' when FCM initialised; otherwise why it did not."""
    return _fcm_state


def fcm_failure_reason() -> str | None:
    """What to fix when push will not start (None when it started or is unset)."""
    return _fcm_reason


class _CredentialsError(Exception):
    """Credentials that cannot be used, with a reason safe to show."""


def _service_account(raw: str) -> dict[str, object]:
    """Parse FCM_CREDENTIALS_JSON, forgiving the usual ways a paste goes wrong.

    Hosts take the value as typed, so a value copied from a .env line keeps its
    surrounding quotes, and some dashboards double the backslashes in the
    private key's line breaks. Both are undone here; anything else is reported.
    """
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _CredentialsError(
            "FCM_CREDENTIALS_JSON is not valid JSON. Paste the whole service-account "
            "file, from { to }, with nothing around it."
        ) from exc
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise _CredentialsError(
            "FCM_CREDENTIALS_JSON is JSON but not a Firebase service-account key "
            "(Firebase console > Project settings > Service accounts > Generate new "
            "private key)."
        )
    key = data.get("private_key")
    if isinstance(key, str) and "\\n" in key and "\n" not in key:
        data["private_key"] = key.replace("\\n", "\n")
    return data


def _credentials_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else _ROOT / path


def init_fcm() -> None:
    """Initialize the Firebase app from config. No-op if unconfigured or already done."""
    global _fcm_app, _fcm_state, _fcm_reason
    if _fcm_app is not None:
        return
    _fcm_reason = None
    settings = get_settings()
    if not settings.fcm_configured:
        _fcm_state = "unconfigured"
        log.warning("fcm_not_configured", detail="FCM credentials missing; push disabled")
        return
    try:
        if settings.fcm_credentials_json:
            cred = credentials.Certificate(_service_account(settings.fcm_credentials_json))
        else:
            path = _credentials_path(settings.fcm_credentials_file)
            if not path.is_file():
                # The usual way this goes wrong on a host: the variable was
                # copied from a laptop's .env, and the file it names is
                # gitignored, so it was never deployed.
                raise _CredentialsError(
                    f"FCM_CREDENTIALS_FILE names {path.name}, which is not on this "
                    "server. On a host, set FCM_CREDENTIALS_JSON to the file's "
                    "contents instead."
                )
            cred = credentials.Certificate(str(path))
        _fcm_app = firebase_admin.initialize_app(cred, name=_FCM_APP_NAME)
        _fcm_state = "ready"
        log.info("fcm_initialized")
    except _CredentialsError as exc:
        _fcm_app = None
        _fcm_state = "failed"
        _fcm_reason = str(exc)
        log.error("fcm_init_failed", reason=_fcm_reason)
    except Exception:
        _fcm_app = None
        _fcm_state = "failed"
        _fcm_reason = (
            "The Firebase service-account key was refused. Generate a new private "
            "key in the Firebase console and set FCM_CREDENTIALS_JSON to it."
        )
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


def android_config(*, alert: bool, tag: str | None = None) -> messaging.AndroidConfig:
    """How Android shows the push: the fire channel and its alarm, or an update.

    High priority either way, so it is delivered at once and shown while the app
    is closed. ``tag`` makes a later push about the same thing replace the
    earlier one in the shade instead of stacking under it.
    """
    return messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(
            channel_id=FIRE_CHANNEL if alert else UPDATES_CHANNEL,
            sound=FIRE_SOUND if alert else None,
            default_sound=not alert,
            default_vibrate_timings=True,
            priority="max" if alert else "high",
            visibility="public",
            tag=tag,
        ),
    )


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
        alert: bool = False,
        tag: str | None = None,
    ) -> PushResult:
        """Send a notification to many device tokens; report invalid ones for cleanup.

        ``alert`` sends it to the fire channel, which rings with the fire alarm:
        only for a push that says there is a fire.
        """
        if not tokens or _fcm_app is None:
            return PushResult()

        def _send() -> PushResult:
            message = messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                android=android_config(alert=alert, tag=tag),
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