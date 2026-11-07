"""Authentication endpoints: self-signup, login, refresh, profile, logout.

v8 master context Section 11 (Phase 3): citizen self-signup, session refresh, and
the four-tier login flow (all tiers authenticate the same way; role comes from the
database profile).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Response, status

from app.api.deps import (
    DEACTIVATED_MESSAGE,
    AccessTokenDep,
    AuthClientDep,
    CurrentUser,
    DatabaseDep,
    EmailClientDep,
    SessionUser,
    phone_gate_applies,
)
from app.api.routes.password_reset import schedule_reset_email
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.supabase_auth import AuthError
from app.schemas.auth import (
    AuthenticatedUser,
    ConsoleAccess,
    ConsoleOrganization,
    LanguageUpdateRequest,
    LocationUpdateRequest,
    LoginRequest,
    MeResponse,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RecoverRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.services.access import admin_access
from app.services.disposable_email import ensure_not_disposable
from app.services.phone_verification import PhoneNumberTakenError, normalize_ph_mobile

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

    The mobile number is checked before the account is made: a malformed one is
    a 400 and one another account already verified is a 409, so neither leaves
    behind an account that can never pass the phone gate. It is stored in E.164;
    proving it is the phone's is the next step, POST /verification/phone/request.

    An email from a throwaway service is refused first, a 400
    ``disposable_email``: the account would lose its sign-in and password reset
    within the hour (app/services/disposable_email.py).
    """
    ensure_not_disposable(str(payload.email))
    mobile = normalize_ph_mobile(payload.mobile) if payload.mobile else None
    if mobile is not None and await _verified_owner_email(db, mobile) is not None:
        raise PhoneNumberTakenError(
            "This number is already used by another RepLiT account. Sign in with it, "
            "or use a different number."
        )
    metadata = {"full_name": payload.full_name} if payload.full_name else None
    data = await auth.sign_up(email=str(payload.email), password=payload.password, data=metadata)
    if "access_token" not in data:
        raise BadRequestError(
            "Account created but no session returned — 'Confirm email' is enabled. "
            "Disable it in Supabase Auth settings (or confirm via email) to log in."
        )
    token = _to_token_response(data)
    if mobile or payload.date_of_birth or payload.gender:
        await db.execute(
            """
            update public.users
               set mobile = $2, date_of_birth = $3, gender = $4, updated_at = now()
             where id = $1
            """,
            token.user_id,
            mobile,
            payload.date_of_birth,
            payload.gender,
        )
    log.info("user_signed_up")
    return token


async def _verified_owner_email(db: Database, phone: str) -> str | None:
    """The email of the account that verified ``phone``, if any account has."""
    email = await db.fetchval(
        "select email from public.users where phone = $1 and phone_verified", phone
    )
    return None if email is None else str(email)


@router.post(
    "/login", response_model=TokenResponse, summary="Log in with email or mobile number"
)
async def login(payload: LoginRequest, auth: AuthClientDep, db: DatabaseDep) -> TokenResponse:
    """Authenticate with a password and return a session (all four tiers).

    Accounts live in Supabase Auth by email, so a mobile number is first turned
    into the email of the account that *verified* it — one account at most, by
    the unique index. A number no account verified gets exactly the refusal a
    wrong password gets, so this cannot be used to find out which numbers are
    registered. Staff have no verified number and keep signing in by email.
    """
    if payload.phone is not None:
        found = await _verified_owner_email(db, normalize_ph_mobile(payload.phone))
        if found is None:
            log.info("login_phone_unmatched")
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        email = found
    else:
        email = str(payload.email)
    try:
        data = await auth.sign_in_with_password(email=email, password=payload.password)
    except AuthError as exc:
        # Supabase Auth says "User is banned" for an account a coordinator
        # deactivated; say it the way a responder would understand.
        if "banned" in exc.message.lower():
            log.info("login_deactivated_account")
            raise AuthError(DEACTIVATED_MESSAGE, details=exc.details) from exc
        raise
    log.info("user_logged_in", method="phone" if payload.phone else "email")
    return _to_token_response(data)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh session")
async def refresh(payload: RefreshRequest, auth: AuthClientDep) -> TokenResponse:
    """Exchange a refresh token for a fresh session."""
    data = await auth.refresh_session(refresh_token=payload.refresh_token)
    return _to_token_response(data)


@router.post("/recover", response_model=MessageResponse, summary="Send a password-reset email")
async def recover(
    payload: RecoverRequest,
    auth: AuthClientDep,
    email: EmailClientDep,
    db: DatabaseDep,
    background: BackgroundTasks,
) -> MessageResponse:
    """Email a password-reset link. Generic response (no account enumeration).

    The link lands on /auth/reset-password, and the email goes through Brevo:
    Supabase's own mailer only delivers to the project's team, and with no
    redirect its links opened the default Site URL, http://localhost:3000. It is
    sent after the response, so timing does not tell which addresses exist.

    A staff account at @replit.com, named by its sign-in or its personal email,
    gets its link at the personal email (routes/staff_email.py).
    """
    schedule_reset_email(background, auth, email, str(payload.email), db)
    return MessageResponse(message="If that email is registered, a reset link has been sent.")


@router.get("/me", response_model=MeResponse, summary="Current user profile")
async def me(user: SessionUser) -> MeResponse:
    """Return the authenticated user's profile (role/agency/verified_percent from DB).

    Reachable before the phone gate is passed — it is how the app learns it has
    to show the gate (``phone_verification_required``). For an Admin it also
    says what the Admin console may offer it (``console``): its organisation,
    the agencies it acts for, and its permissions (app/services/access.py).
    """
    return MeResponse.model_validate(
        {
            **user.model_dump(),
            "phone_verification_required": phone_gate_applies(user),
            "console": _console_of(user),
        }
    )


def _console_of(user: AuthenticatedUser) -> ConsoleAccess | None:
    """An Admin's standing in the console, or None for everyone else."""
    access = admin_access(user)
    if access is None:
        return None
    organization = None
    if access.organization_id is not None:
        organization = ConsoleOrganization(
            id=access.organization_id,
            name=access.organization_name,
            agency_type=access.agency,
            is_central_hub=access.variant == "central",
        )
    return ConsoleAccess(
        variant=access.variant,
        scope=access.scope,
        organization=organization,
        act_agencies=None if access.act_agencies is None else list(access.act_agencies),
        permissions=sorted(access.permissions),
    )


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
    """Store the caller's location so they receive 150 m neighborhood alerts.

    public.users.location is generated from latitude/longitude, so updating those
    columns refreshes the geography used by the neighborhood-notification worker.
    location_updated_at says how fresh it is: the worker ignores a location older
    than NEIGHBORHOOD_LOCATION_MAX_AGE_MINUTES.
    """
    await db.execute(
        "update public.users set latitude = $2, longitude = $3, "
        "location_updated_at = now(), last_active_at = now() "
        "where id = $1",
        user.id,
        payload.latitude,
        payload.longitude,
    )
    log.info("user_location_updated", user_id=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/me/language",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set the language my alerts come in",
)
async def update_my_language(
    payload: LanguageUpdateRequest, user: SessionUser, db: DatabaseDep
) -> Response:
    """English or Tagalog: residents' pushes and inbox rows follow it (citizen_copy).

    Behind the session only, not the phone gate: the app sends it at sign-in,
    before a new resident has verified a number.
    """
    await db.execute(
        "update public.users set language = $2 where id = $1", user.id, payload.language
    )
    log.info("user_language_updated", user_id=str(user.id), language=payload.language)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change my password",
)
async def change_my_password(
    payload: PasswordChangeRequest,
    user: SessionUser,
    token: AccessTokenDep,
    auth: AuthClientDep,
) -> Response:
    """Check the current password, set the new one, sign the other devices out.

    For every role, from the app's Profile and the Admin console's Settings. The
    current password is checked by signing in with it, so a phone left unlocked
    cannot have its password changed. The new one is set with the service key,
    which needs no GoTrue reauthentication nonce. Then every session but this
    one is revoked — the check's own session included — and this device stays
    signed in.

    A wrong current password is a 400, never a 401: the clients read 401 as an
    expired session and would sign the person out. Behind the session only,
    not the phone gate, like the language.
    """
    if payload.new_password == payload.current_password:
        raise BadRequestError(
            "The new password is the same as the current one.", error_code="same_password"
        )
    if not user.email:
        raise BadRequestError(
            "This account has no email to check the password against.",
            error_code="no_email",
        )
    try:
        await auth.sign_in_with_password(email=user.email, password=payload.current_password)
    except AuthError as exc:
        log.info("password_change_wrong_current", user_id=str(user.id))
        raise BadRequestError(
            "The current password is not right.", error_code="wrong_password"
        ) from exc
    await auth.admin_update_user(
        user_id=str(user.id), attributes={"password": payload.new_password}
    )
    try:
        await auth.sign_out(access_token=token, scope="others")
    except (AuthError, ExternalServiceError):
        # The password is changed either way; old sessions then simply run out.
        log.warning("password_change_other_sessions_kept", user_id=str(user.id))
    log.info("user_password_changed", user_id=str(user.id), role=user.role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout(user: SessionUser, token: AccessTokenDep, auth: AuthClientDep) -> Response:
    """Revoke the current session at Supabase Auth."""
    await auth.sign_out(access_token=token)
    log.info("user_logged_out")
    return Response(status_code=status.HTTP_204_NO_CONTENT)