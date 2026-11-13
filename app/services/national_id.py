"""National ID photos are held for one review and no longer.

Object names carry no extension, so a second submission replaces the first
instead of leaving a .png beside a .jpg that nothing would delete.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, SoundCategory, token_versions
from app.integrations.supabase_storage import SupabaseStorageClient
from app.services.citizen_copy import NATIONAL_ID_APPROVED, NATIONAL_ID_RETRY, languages_of
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

BUCKET = "national-ids"


def photo_paths(user_id: UUID) -> dict[str, str]:
    """Where one person's photos go, under the metadata key that records each."""
    return {
        "id_path": f"{user_id}/national_id",
        "selfie_path": f"{user_id}/selfie",
        "qr_path": f"{user_id}/national_id_qr",
    }


async def remove_photos(storage: SupabaseStorageClient, paths: Iterable[str | None]) -> None:
    """Delete the photos at ``paths``. One that is already gone is not an error."""
    for path in paths:
        if path:
            await storage.remove(bucket=BUCKET, path=path)


async def notify_review_decided(
    db: Database, user_id: UUID, *, approved: bool, notes: str | None = None
) -> int:
    """Tell the resident how their review went (inbox + push).

    Their photos are gone by now, so someone asked to try again has to hear it
    and has to read why. Best-effort; returns the devices sent to.
    """
    language = (await languages_of(db, [user_id])).get(user_id, "en")
    if approved:
        title, body = NATIONAL_ID_APPROVED[language]
    else:
        title, fallback = NATIONAL_ID_RETRY[language]
        # The reviewer's own words, as they wrote them, when there are any.
        body = notes or fallback
    # Its own recording, verified or not (v1.12.33: "custom national id
    # verified sound (id verified and rejected)"; it had the phone's tone).
    # The inbox row names it too, for the iPhone, which hears its inbox.
    sound: SoundCategory = "id_verified" if approved else "id_rejected"
    data = {"type": "national_id_reviewed", "sound_category": sound}
    await record_inbox(db, [user_id], "national_id_reviewed", title, body, data)
    token_rows = await db.fetch(
        "select fcm_token, app_version from public.device_tokens "
        "where user_id = $1 and is_active",
        user_id,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if not tokens:
        return 0
    result = await PushService().send_to_tokens(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "national_id_reviewed"},
        sound=sound,
        tag="national-id-review",
        versions=token_versions(token_rows),
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info("national_id_review_notified", user_id=str(user_id), devices=len(tokens))
    return len(tokens)
