"""Authentication endpoints: self-signup, login, refresh, profile, logout.

v8 master context Section 11 (Phase 3): citizen self-signup, session refresh, and
the four-tier login flow (all tiers authenticate the same way; role comes from the
database profile).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import AccessTokenDep, AuthClientDep, CurrentUser, DatabaseDep
from app.core.exceptions import AppError, BadRequestError
from app.core.logging import get_logger
from app.schemas.auth import (
    AuthenticatedUser,
    LocationUpdateRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RecoverRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse

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
async def signup(
    payload: SignupRequest, auth: AuthClientDep, db: DatabaseDep
) -> TokenResponse:
    """Create a general-user account and return a session.

    The handle_new_user() DB trigger provisions the public.users row as
    general_user; role elevation is admin-only (Part 5). Optional profile fields
    (mobile / DOB / gender) are persisted onto that row right after signup.
    """
    metadata = {"full_name": payload.full_name} if payload.full_name else None
    data = await auth.sign_up(email=str(payload.email), password=payload.password, data=metadata)
    if "access_token" not in data:
        raise BadRequestError(
            "Account created but no session returned — 'Confirm email' is enabled. "
            "Disable it in Supabase Auth settings (or confirm via email) to log in."
        )
    token = _to_token_response(data)
    if payload.mobile or payload.date_of_birth or payload.gender:
        await db.execute(
            """
            update public.users
               set mobile = $2, date_of_birth = $3, gender = $4, updated_at = now()
             where id = $1
            """,
            token.user_id,
            payload.mobile,
            payload.date_of_birth,
            payload.gender,
        )
    log.info("user_signed_up")
    return token


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


@router.post("/recover", response_model=MessageResponse, summary="Send a password-reset email")
async def recover(payload: RecoverRequest, auth: AuthClientDep) -> MessageResponse:
    """Send a GoTrue password-reset email. Generic response (no account enumeration)."""
    try:
        await auth.recover(email=str(payload.email))
    except AppError:
        log.info("password_recover_failed_silently")
    return MessageResponse(message="If that email is registered, a reset link has been sent.")


@router.get("/me", response_model=AuthenticatedUser, summary="Current user profile")
async def me(user: CurrentUser) -> AuthenticatedUser:
    """Return the authenticated user's profile (role/agency/verified_percent from DB)."""
    return user


@router.patch("/me/profile", response_model=AuthenticatedUser, summary="Update my profile")
async def update_my_profile(
    payload: ProfileUpdateRequest, user: CurrentUser, db: DatabaseDep
) -> AuthenticatedUser:
    """Update the caller's editable profile fields (full name / mobile / DOB / gender).

    Omitted (null) fields are left unchanged via COALESCE.
    """
    row = await db.fetchrow(
        """
        update public.users
           set full_name     = coalesce($2, full_name),
               mobile        = coalesce($3, mobile),
               date_of_birth = coalesce($4, date_of_birth),
               gender        = coalesce($5, gender),
               updated_at    = now()
         where id = $1
        returning id, email, phone, role, agency_type, verified_percent, badge,
                  full_name, primary_org_id, mobile, date_of_birth, gender
        """,
        user.id,
        payload.full_name,
        payload.mobile,
        payload.date_of_birth,
        payload.gender,
    )
    assert row is not None
    log.info("profile_updated", user_id=str(user.id))
    return AuthenticatedUser.model_validate(dict(row))


@router.post(
    "/me/location",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update my last-known location",
)
async def update_my_location(
    payload: LocationUpdateRequest, user: CurrentUser, db: DatabaseDep
) -> Response:
    """Store the caller's location so they receive 300 m neighborhood alerts.

    public.users.location is generated from latitude/longitude, so updating those
    columns refreshes the geography used by the neighborhood-notification worker.
    """
    await db.execute(
        "update public.users set latitude = $2, longitude = $3, last_active_at = now() "
        "where id = $1",
        user.id,
        payload.latitude,
        payload.longitude,
    )
    log.info("user_location_updated", user_id=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout(user: CurrentUser, token: AccessTokenDep, auth: AuthClientDep) -> Response:
    """Revoke the current session at Supabase Auth."""
    await auth.sign_out(access_token=token)
    log.info("user_logged_out")
    return Response(status_code=status.HTTP_204_NO_CONTENT)