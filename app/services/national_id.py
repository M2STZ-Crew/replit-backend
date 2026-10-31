"""National ID photos are held for one review and no longer.

Object names carry no extension, so a second submission replaces the first
instead of leaving a .png beside a .jpg that nothing would delete.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService
from app.integrations.supabase_storage import SupabaseStorageClient
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
    if approved:
        title = "National ID verified"
        body = "Your verification went up. Your photos have been deleted."
    else:
        title = "Try your National ID again"
        body = notes or "It was not accepted. Send new photos from the app."
    data = {"type": "national_id_reviewed"}
    await record_inbox(db, [user_id], "national_id_reviewed", title, body, data)
    token_rows = await db.fetch(
        "select fcm_token from public.device_tokens where user_id = $1 and is_active",
        user_id,
    )
    tokens = [t["fcm_token"] for t in token_rows]
    if not tokens:
        return 0
    result = await PushService().send_to_tokens(
        tokens=tokens, title=title, body=body, data=data, tag="national-id-review"
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false "
            "where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info("national_id_review_notified", user_id=str(user_id), devices=len(tokens))
    return len(tokens)
