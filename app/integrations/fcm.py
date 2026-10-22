"""Firebase Cloud Messaging: app init + generic push service.

The Firebase Admin SDK is synchronous, so sends run in a worker thread. The push
service is FCM-only (no DB): callers fetch device tokens / choose topics and pass
them in. Used by Phase 8 (neighborhood alerts) and Phase 9 (lifecycle pushes).

v1.12.6: Android notification channels, created by the app (MainActivity.kt),
pick the sound. And when FCM will not start, the server says why, in words
safe to show anyone (no credential content).

v1.12.9: one channel per sound, playing the recordings chosen for the pilot.
Staff hear their own agency's sound (fire for Fire Volunteers and BFP,
police, medical, barangay); a neighbour's first alert plays the fire sound;
a resident's other pushes play the citizen sound. A silent channel only
vibrates, for the coordinator's reminder pings. Every push with a sound also
says which in its data (``sound_category``), so the app plays the same
recording when the push arrives while it is open.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
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

SoundCategory = Literal["fire", "police", "medical", "barangay", "citizen"]

# The channels the app creates (android/app/src/main/kotlin/.../MainActivity.kt)
# and the recording each plays (res/raw/sound_<category>.mp3). Android picks
# the sound from the channel; ``sound`` is for phones before Android 8. A
# channel's sound is fixed once the phone has made it, so a new recording
# needs a new channel id here and in the app.
SOUND_CHANNELS: dict[SoundCategory, str] = {
    "fire": "alert_fire",
    "police": "alert_police",
    "medical": "alert_medical",
    "barangay": "alert_barangay",
    "citizen": "citizen_updates",
}
UPDATES_CHANNEL = "updates"
SILENT_CHANNEL = "silent_ping"

# Whose sound a staff member hears: their own agency's. The two fire agencies
# share the fire recording.
_AGENCY_SOUND: dict[str, SoundCategory] = {
    "fire_volunteer": "fire",
    "bfp": "fire",
    "police": "police",
    "medical": "medical",
    "barangay": "barangay",
}


def sound_for_agency(agency: str | None) -> SoundCategory:
    """The sound a staff member of ``agency`` hears for their alerts."""
    return _AGENCY_SOUND.get(agency or "", "fire")

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


def _json_problem(text: str, exc: json.JSONDecodeError) -> str:
    """Where a pasted value stops being JSON, without quoting any of it."""
    if not text.startswith("{"):
        return "it does not start with {"
    if not text.endswith("}"):
        return "it stops before the closing } (was only part of the file pasted?)"
    return f"{exc.msg} at line {exc.lineno}, column {exc.colno}"


def _service_account(raw: str) -> dict[str, object]:
    """Parse FCM_CREDENTIALS_JSON, forgiving the usual ways a paste goes wrong.

    Hosts take the value as typed, so a value copied from a .env line keeps its
    surrounding quotes; some dashboards double the backslashes in the private
    key's line breaks, and some turn them into real line breaks, which strict
    JSON refuses inside a string. A value saved base64-encoded (one line, so
    nothing can mangle it) is decoded. All of these are undone here; anything
    else is reported with where it went wrong, never with what it says.
    """
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    if text and not text.startswith("{"):
        try:
            decoded = base64.b64decode(text, validate=True).decode("utf-8").strip()
        except (binascii.Error, UnicodeDecodeError):
            decoded = ""
        if decoded.startswith("{"):
            text = decoded
    try:
        # strict=False: real line breaks inside the private key are accepted.
        data = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        raise _CredentialsError(
            f"FCM_CREDENTIALS_JSON is not valid JSON: {_json_problem(text, exc)}. "
            "Paste the whole service-account file, from { to }, with nothing "
            "around it — or use a Render Secret File and set FCM_CREDENTIALS_FILE "
            "to its path (/etc/secrets/<name>.json)."
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


def android_config(
    *,
    sound: SoundCategory | None = None,
    silent: bool = False,
    tag: str | None = None,
) -> messaging.AndroidConfig:
    """How Android shows the push: which channel, and so which sound.

    ``sound`` names a recording (its channel plays it); ``silent`` only
    vibrates; neither is an update with the phone's own tone. High priority
    either way, so it is delivered at once and shown while the app is closed.
    ``tag`` makes a later push about the same thing replace the earlier one in
    the shade instead of stacking under it.
    """
    if silent:
        channel, file, phone_tone, urgent = SILENT_CHANNEL, None, False, True
    elif sound is not None:
        channel, file, phone_tone = SOUND_CHANNELS[sound], f"sound_{sound}", False
        urgent = sound != "citizen"
    else:
        channel, file, phone_tone, urgent = UPDATES_CHANNEL, None, True, False
    return messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(
            channel_id=channel,
            sound=file,
            default_sound=phone_tone,
            default_vibrate_timings=True,
            priority="max" if urgent else "high",
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
        sound: SoundCategory | None = None,
        silent: bool = False,
        tag: str | None = None,
    ) -> PushResult:
        """Send a notification to many device tokens; report invalid ones for cleanup.

        ``sound`` plays that category's recording (see [android_config]);
        ``silent`` only vibrates. The data says which, for the open app.
        """
        if not tokens or _fcm_app is None:
            return PushResult()
        payload = dict(data or {})
        if silent:
            payload["silent"] = "true"
        elif sound is not None:
            payload["sound_category"] = sound

        def _send() -> PushResult:
            message = messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(title=title, body=body),
                data=payload,
                android=android_config(sound=sound, silent=silent, tag=tag),
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