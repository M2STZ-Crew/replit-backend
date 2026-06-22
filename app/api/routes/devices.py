"""Device-token (FCM) management endpoints (Phase 5).

Multi-device per user; tokens are unique. A test endpoint exercises the push path
and auto-deactivates tokens FCM reports as unregistered.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DatabaseDep, PushServiceDep
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.device import DeviceTokenCreate, DeviceTokenResponse

log = get_logger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or refresh a device token",
)
async def register_device(
    payload: DeviceTokenCreate, user: CurrentUser, db: DatabaseDep
) -> DeviceTokenResponse:
    """Upsert the caller's FCM token (re-registering reassigns it to this user)."""
    row = await db.fetchrow(
        """
        insert into public.device_tokens
            (user_id, fcm_token, platform, device_id, device_name, app_version,
             is_active, last_used_at)
        values ($1, $2, $3::public.device_platform, $4, $5, $6, true, now())
        on conflict (fcm_token) do update
           set user_id = $1, platform = $3::public.device_platform, device_id = $4,
               device_name = $5, app_version = $6, is_active = true, last_used_at = now()
        returning id, fcm_token, platform, device_name, is_active, created_at
        """,
        user.id,
        payload.fcm_token,
        payload.platform,
        payload.device_id,
        payload.device_name,
        payload.app_version,
    )
    assert row is not None
    log.info("device_registered", user_id=str(user.id), platform=payload.platform)
    return DeviceTokenResponse.model_validate(dict(row))


@router.get("", response_model=list[DeviceTokenResponse], summary="List my device tokens")
async def list_devices(user: CurrentUser, db: DatabaseDep) -> list[DeviceTokenResponse]:
    """List the caller's active device tokens."""
    rows = await db.fetch(
        """
        select id, fcm_token, platform, device_name, is_active, created_at
        from public.device_tokens
        where user_id = $1 and is_active
        order by last_used_at desc nulls last
        """,
        user.id,
    )
    return [DeviceTokenResponse.model_validate(dict(r)) for r in rows]


@router.delete(
    "/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister a device token",
)
async def unregister_device(token: str, user: CurrentUser, db: DatabaseDep) -> Response:
    """Delete one of the caller's device tokens."""
    await db.execute(
        "delete from public.device_tokens where fcm_token = $1 and user_id = $2",
        token,
        user.id,
    )
    log.info("device_unregistered", user_id=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=MessageResponse, summary="Send a test push to my devices")
async def send_test_push(
    user: CurrentUser, db: DatabaseDep, push: PushServiceDep
) -> MessageResponse:
    """Send a test notification to the caller's active tokens; deactivate dead ones."""
    rows = await db.fetch(
        "select fcm_token from public.device_tokens where user_id = $1 and is_active",
        user.id,
    )
    tokens = [r["fcm_token"] for r in rows]
    if not tokens:
        raise BadRequestError("No active device tokens registered.")
    result = await push.send_to_tokens(
        tokens=tokens,
        title="RepLiT test",
        body="Push notifications are working.",
        data={"type": "test"},
    )
    if result.invalid_tokens:
        await db.execute(
            "update public.device_tokens set is_active = false where fcm_token = any($1::text[])",
            result.invalid_tokens,
        )
    log.info(
        "test_push_sent",
        user_id=str(user.id),
        success=result.success_count,
        failed=result.failure_count,
    )
    return MessageResponse(
        message=f"Sent to {result.success_count} device(s); {result.failure_count} failed."
    )