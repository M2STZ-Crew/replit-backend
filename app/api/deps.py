"""Shared FastAPI dependencies (resources + authentication + RBAC).

Provides Annotated dependency aliases used across the API: the database pool, the
shared HTTP client, the authenticated current user, and role-gated variants.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, PhoneNotVerifiedError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import Database, database
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.deepseek_ai import DeepSeekClient
from app.integrations.didit_kyc import DiditKYCClient
from app.integrations.fcm import PushService
from app.integrations.semaphore_sms import SemaphoreClient
from app.integrations.supabase_auth import SupabaseAuthClient
from app.integrations.supabase_storage import SupabaseStorageClient
from app.schemas.auth import AuthenticatedUser


# --------------------------------------------------------------------------- #
# Resource dependencies
# --------------------------------------------------------------------------- #
async def get_database() -> Database:
    """Return the shared Database (asyncpg pool wrapper)."""
    return database


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient created during app startup."""
    return cast(httpx.AsyncClient, request.app.state.http_client)


def get_auth_client(request: Request) -> SupabaseAuthClient:
    """Return a Supabase Auth (GoTrue) client bound to the shared HTTP client."""
    return SupabaseAuthClient(cast(httpx.AsyncClient, request.app.state.http_client))


def get_storage_client(request: Request) -> SupabaseStorageClient:
    """Return a Supabase Storage client bound to the shared HTTP client."""
    return SupabaseStorageClient(cast(httpx.AsyncClient, request.app.state.http_client))


def get_didit_client(request: Request) -> DiditKYCClient:
    """Return a Didit.me KYC client bound to the shared HTTP client."""
    return DiditKYCClient(cast(httpx.AsyncClient, request.app.state.http_client))

def get_push_service() -> PushService:
    """Return the FCM push service (uses the app initialized at startup)."""
    return PushService()

def get_email_client() -> BrevoEmailClient:
    """Return a Brevo email client (uses SMTP settings)."""
    return BrevoEmailClient()

def get_semaphore_client(request: Request) -> SemaphoreClient:
    """Return a Semaphore SMS client bound to the shared HTTP client."""
    return SemaphoreClient(cast(httpx.AsyncClient, request.app.state.http_client))

def get_deepseek_client(request: Request) -> DeepSeekClient:
    """Return a DeepSeek summarization client bound to the shared HTTP client."""
    return DeepSeekClient(cast(httpx.AsyncClient, request.app.state.http_client))

DatabaseDep = Annotated[Database, Depends(get_database)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
AuthClientDep = Annotated[SupabaseAuthClient, Depends(get_auth_client)]
StorageClientDep = Annotated[SupabaseStorageClient, Depends(get_storage_client)]
DiditClientDep = Annotated[DiditKYCClient, Depends(get_didit_client)]
PushServiceDep = Annotated[PushService, Depends(get_push_service)]
EmailClientDep = Annotated[BrevoEmailClient, Depends(get_email_client)]
SemaphoreDep = Annotated[SemaphoreClient, Depends(get_semaphore_client)]
DeepSeekClientDep = Annotated[DeepSeekClient, Depends(get_deepseek_client)]

# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")


async def get_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """Return the raw Bearer access token, or 401 if absent."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing or malformed Authorization header.")
    return credentials.credentials


AccessTokenDep = Annotated[str, Depends(get_access_token)]


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DatabaseDep,
    http_client: HttpClientDep,
) -> AuthenticatedUser:
    """Validate the Bearer token and load the authenticated user from the database."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing or malformed Authorization header.")

    claims = await decode_access_token(credentials.credentials, http_client)
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise UnauthorizedError("Token is missing the subject (sub) claim.")
    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise UnauthorizedError("Token subject is not a valid user id.") from exc

    row = await db.fetchrow(
        """
        select id, email, phone, role, agency_type, verified_percent, badge,
               full_name, primary_org_id, mobile, date_of_birth, gender, phone_verified
        from public.users
        where id = $1
        """,
        user_id,
    )
    if row is None:
        raise UnauthorizedError("Authenticated user has no profile record.")
    user = AuthenticatedUser.model_validate(dict(row))
    request.state.actor_id = user.id
    request.state.actor_role = user.role
    request.state.actor_agency = user.agency_type
    return user


def phone_gate_applies(user: AuthenticatedUser) -> bool:
    """True when this account must verify a mobile number before using the app.

    Only citizens are gated. Staff accounts come from a reviewed affiliate
    application that an Admin approves, so they are vouched for another way —
    and no staff account has ever verified a phone, so gating them would lock
    out every coordinator and responder at once.

    Shared by the HTTP dependency and the WebSocket handshake, so the two cannot
    disagree about who is let in.
    """
    return (
        get_settings().require_citizen_phone_verification
        and user.role == "general_user"
        and not user.phone_verified
    )


async def get_verified_user(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """The current user, refused with 403 if they are a citizen yet to verify.

    This is what CurrentUser resolves to, so every route that takes CurrentUser
    is gated by default and a new citizen route cannot forget to be. The check
    reads users.phone_verified, which only a correct SMS code can set (via the
    recompute_user_verification trigger) — nothing a client sends, stores or
    edits in its token can change it.
    """
    if phone_gate_applies(user):
        raise PhoneNotVerifiedError(
            "Verify your mobile number before using your RepLiT account. We will "
            "text you a code.",
        )
    return user


# Any authenticated account, verified or not. Only for the handful of routes an
# unverified citizen needs in order to become verified: reading their own
# profile, signing out, and requesting or checking the SMS code.
SessionUser = Annotated[AuthenticatedUser, Depends(get_current_user)]

# The default. Gated for citizens who have not yet verified their phone.
CurrentUser = Annotated[AuthenticatedUser, Depends(get_verified_user)]


# --------------------------------------------------------------------------- #
# Role-based access control
# --------------------------------------------------------------------------- #
def require_role(*roles: str) -> Callable[[AuthenticatedUser], Awaitable[AuthenticatedUser]]:
    """Build a dependency that requires the current user to hold one of ``roles``.

    Mirrors the database-layer RBAC (Section 6) at the FastAPI layer; raises 403 on
    mismatch.
    """
    allowed = set(roles)

    async def dependency(user: CurrentUser) -> AuthenticatedUser:
        if user.role not in allowed:
            raise ForbiddenError(
                "You do not have permission to perform this action.",
                details={"required_roles": sorted(allowed), "your_role": user.role},
            )
        return user

    return dependency


AdminUser = Annotated[AuthenticatedUser, Depends(require_role("admin"))]
StaffUser = Annotated[
    AuthenticatedUser, Depends(require_role("admin", "sub_admin", "response_team"))
]