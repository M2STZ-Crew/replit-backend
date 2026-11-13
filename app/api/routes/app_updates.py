"""Ask for "New Update!" now (backend v1.12.32).

13 November 2026: "the "new update" push notification doesn't work on my
android phone". It was sent, but only at the service's next check, every 10
minutes: app 1.12.40 came out at 12:16:56, by 12:18 the phone had installed it
from the update banner, and the 12:26 check found it up to date. The app's
release workflow (.github/workflows/android-release.yml in replit-android)
now asks for a check as soon as it has published, so phones on an older
version hear of it within seconds.

Public, and it takes nothing: the release is read from GitHub, as the
scheduled check reads it, never from the caller, and each person is told once
per version. A burst of asks is answered from the last check
(``ASK_COOLDOWN_SECONDS``).
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import DatabaseDep, HttpClientDep, PushServiceDep
from app.schemas.app_update import AppUpdateCheckResponse
from app.workers.app_updates import check_now

router = APIRouter(prefix="/app-updates", tags=["app-updates"])


@router.post(
    "/check",
    response_model=AppUpdateCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check for a new app release now",
)
async def check_for_release(
    db: DatabaseDep, push: PushServiceDep, http: HttpClientDep
) -> AppUpdateCheckResponse:
    """Read the newest Android release now and tell everyone on an older
    version ("New Update!"), as the scheduled check does. Public: the release
    workflow calls it once it has published, and asks again until the
    version it published is the one this answers with.
    """
    checked = await check_now(db, push, http, asked=True)
    return AppUpdateCheckResponse(version=checked.version)
