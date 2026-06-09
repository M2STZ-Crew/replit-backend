"""Authentication endpoints: self-signup, login, refresh, profile, logout.

v8 master context Section 11 (Phase 3): citizen self-signup, session refresh, and
the four-tier login flow (all tiers authenticate the same way; role comes from the
database profile).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import AccessTokenDep, AuthClientDep, CurrentUser
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_token_response(data: dict[str, Any]) -> TokenResponse:
    """Map a GoTrue session payload to our TokenResponse schema."""
    user = data.get("user") or {}
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        token_type=data.get("token_type", "bearer"),
        expires_in=data.get("expires_in"),
        expires_at=data.get("expires_at"),
        user_id=user.get("id"),
        email=user.get("email"),
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Citizen self-signup",
)
async def signup(payload: SignupRequest, auth: AuthClientDep) -> TokenResponse:
    """Create a general-user account and return a session.

    The handle_new_user() DB trigger provisions the public.users row as
    general_user; role elevation is admin-only (Part 5).
    """
    metadata = {"full_name": payload.full_name} if payload.full_name else None
    data = await auth.sign_up(email=str(payload.email), password=payload.password, data=metadata)
    if "access_token" not in data:
        raise BadRequestError(
            "Account created but no session returned — 'Confirm email' is enabled. "
            "Disable it in Supabase Auth settings (or confirm via email) to log in."
        )
    log.info("user_signed_up")
    return _to_token_response(data)


@router.post("/login", response_model=TokenResponse, summary="Email/password login")
async def login(payload: LoginRequest, auth: AuthClientDep) -> TokenResponse:
    """Authenticate with email + password and return a session (all four tiers)."""
    data = await auth.sign_in_with_password(email=str(payload.email), password=payload.password)
    log.info("user_logged_in")
    return _to_token_response(data)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh session")
async def refresh(payload: RefreshRequest, auth: AuthClientDep) -> TokenResponse:
    """Exchange a refresh token for a fresh session."""
    data = await auth.refresh_session(refresh_token=payload.refresh_token)
    return _to_token_response(data)


@router.get("/me", response_model=AuthenticatedUser, summary="Current user profile")
async def me(user: CurrentUser) -> AuthenticatedUser:
    """Return the authenticated user's profile (role/agency/verified_percent from DB)."""
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout(user: CurrentUser, token: AccessTokenDep, auth: AuthClientDep) -> Response:
    """Revoke the current session at Supabase Auth."""
    await auth.sign_out(access_token=token)
    log.info("user_logged_out")
    return Response(status_code=status.HTTP_204_NO_CONTENT)