"""In-app notification inbox writes.

A thin helper to persist one ``public.notifications`` row per recipient, called
alongside the FCM pushes so users keep a history they can browse in-app. jsonb is
passed as a JSON string (no codec registered — see DB conventions).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database

log = get_logger(__name__)


async def record_inbox(
    db: Database,
    user_ids: Sequence[UUID],
    type_: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> int:
    """Insert one inbox row per user. Best-effort; returns the number of rows."""
    ids = list(dict.fromkeys(user_ids))  # de-dupe, preserve order
    if not ids:
        return 0
    await db.execute(
        """
        insert into public.notifications (user_id, type, title, body, data)
        select uid, $2, $3, $4, $5::jsonb from unnest($1::uuid[]) as uid
        """,
        ids,
        type_,
        title,
        body,
        json.dumps(data or {}),
    )
    log.info("inbox_recorded", inbox_type=type_, recipients=len(ids))
    return len(ids)
