"""A coordinator's responder accounts (v1.12.4).

Every sub-admin — a Fire Volunteer or BFP coordinator in the app, a police,
medical or barangay one in the web Observer Console — makes the Response Team
accounts of their own agency and team, and looks after them:

* **Create.** The address follows the account directory's rule —
  ``jdelacruz.resfir@replit.com``, numbered after the surname when taken
  (app/services/responder_accounts.py) — and the password is generated and
  returned once, for the coordinator to hand over in person. @replit.com has no
  mailboxes, so nothing is emailed and no e-mail reset can reach it.
* **Reset password.** A new temporary password, returned once.
* **Deactivate / reactivate.** The account keeps its history but cannot sign
  in: Supabase Auth bans it, the API refuses it on every request and the
  socket, its pushes stop, and any response it is on is released.

A coordinator sees and manages only responders of their own agency — of their
own team when they have one, else the agency's responders with no team.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, DatabaseDep, SubAdminUser
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.schemas.team import (
    ResponderCreateRequest,
    ResponderCredentials,
    ResponderEmailPreview,
    TeamResponder,
)
from app.services.audit import record_audit
from app.services.phone_verification import normalize_ph_mobile
from app.services.responder_accounts import (
    AGENCY_CODES,
    InvalidNameError,
    like_pattern,
    responder_email,
    temporary_password,
)

log = get_logger(__name__)

router = APIRouter(prefix="/team", tags=["team"])

# Long enough to mean "until reactivated" (Supabase Auth takes a duration).
_BAN_FOREVER = "876000h"

_RESPONDER_COLS = """
    u.id, u.full_name, u.email, u.mobile, u.agency_type::text as agency_type,
    u.is_active, u.created_at, u.deactivated_at,
    exists (
        select 1 from public.dispatch_logs d
        where d.responder_id = u.id and d.status = 'active'
    ) as responding
"""

# Responders of the caller's agency, on the caller's team — or, for a
# coordinator with no team, the agency's responders with none.
_IN_SCOPE = (
    "u.role = 'response_team' and u.agency_type = $1::public.agency_type "
    "and u.primary_org_id is not distinct from $2"
)


def _agency(user: AuthenticatedUser) -> str:
    """The agency the caller makes responders for."""
    agency = user.agency_type
    if agency not in AGENCY_CODES:
        raise ForbiddenError("Your account has no agency to make responder accounts for.")
    return str(agency)


async def _taken(db: Database, first: str, last: str, agency: str) -> list[str]:
    """Every address this person's could collide with."""
    rows = await db.fetch(
        "select email from public.users where lower(email) like $1",
        like_pattern(first, last, agency),
    )
    return [str(r["email"]) for r in rows if r["email"]]


async def _responder(db: Database, user: AuthenticatedUser, responder_id: UUID) -> TeamResponder:
    """One responder on the caller's roster, or 404 — another team's is not found."""
    row = await db.fetchrow(
        f"select {_RESPONDER_COLS} from public.users u where u.id = $3 and {_IN_SCOPE}",
        _agency(user),
        user.primary_org_id,
        responder_id,
    )
    if row is None:
        raise NotFoundError("No responder of yours has that id.")
    return TeamResponder.model_validate(dict(row))


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get(
    "/responders",
    response_model=list[TeamResponder],
    summary="List my responder accounts (coordinator)",
)
async def list_responders(user: SubAdminUser, db: DatabaseDep) -> list[TeamResponder]:
    """The caller's responders: active first, then by name."""
    rows = await db.fetch(
        f"select {_RESPONDER_COLS} from public.users u where {_IN_SCOPE} "
        "order by u.is_active desc, u.full_name nulls last, u.email",
        _agency(user),
        user.primary_org_id,
    )
    return [TeamResponder.model_validate(dict(r)) for r in rows]


@router.get(
    "/responders/email-preview",
    response_model=ResponderEmailPreview,
    summary="The address a new responder with this name would get",
)
async def preview_email(
    user: SubAdminUser,
    db: DatabaseDep,
    first_name: str = Query(min_length=1, max_length=60),
    last_name: str = Query(min_length=1, max_length=60),
) -> ResponderEmailPreview:
    """Shown on the form as the name is typed; the create takes the next free one."""
    agency = _agency(user)
    try:
        email = responder_email(
            first_name, last_name, agency, await _taken(db, first_name, last_name, agency)
        )
    except InvalidNameError as exc:
        raise BadRequestError(str(exc)) from exc
    return ResponderEmailPreview(email=email)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@router.post(
    "/responders",
    response_model=ResponderCredentials,
    status_code=status.HTTP_201_CREATED,
    summary="Create a responder account (coordinator)",
)
async def create_responder(
    payload: ResponderCreateRequest,
    request: Request,
    user: SubAdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> ResponderCredentials:
    """A Response Team account of the caller's agency and team.

    Returns the address and a temporary password — once; the coordinator hands
    them over. If two coordinators name the same person at once, the second
    takes the next number rather than failing.
    """
    agency = _agency(user)
    first = payload.first_name.strip()
    last = payload.last_name.strip()
    mobile = (
        normalize_ph_mobile(payload.mobile)
        if payload.mobile and payload.mobile.strip()
        else None
    )
    full_name = f"{first} {last}"
    password = temporary_password()

    created: dict[str, Any] | None = None
    email = ""
    for attempt in range(3):
        try:
            email = responder_email(first, last, agency, await _taken(db, first, last, agency))
        except InvalidNameError as exc:
            raise BadRequestError(str(exc)) from exc
        try:
            created = await auth.admin_create_user(
                email=email,
                password=password,
                email_confirm=True,
                user_metadata={"full_name": full_name},
            )
            break
        except BadRequestError as exc:
            # Taken between the check and the create: take the next number.
            if "already" not in exc.message.lower() or attempt == 2:
                raise
            log.info("responder_email_race", email=email)
    assert created is not None
    raw_id = created.get("id") or (created.get("user") or {}).get("id")
    if not isinstance(raw_id, str):
        raise ExternalServiceError("Account created but no id was returned by Supabase Auth.")
    new_id = UUID(raw_id)

    try:
        async with db.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                update public.users u
                   set role = 'response_team',
                       agency_type = $2::public.agency_type,
                       full_name = $3,
                       primary_org_id = $4,
                       mobile = $5,
                       created_by = $6,
                       is_active = true,
                       updated_at = now()
                 where u.id = $1
                 returning {_RESPONDER_COLS}
                """,
                new_id,
                agency,
                full_name,
                user.primary_org_id,
                mobile,
                user.id,
            )
            if row is None:
                raise ExternalServiceError("Account created but its profile was not found.")
            await record_audit(
                conn,
                request,
                user,
                action="user.responder_created",
                entity_type="user",
                entity_id=new_id,
                after_state={
                    "email": email,
                    "role": "response_team",
                    "agency": agency,
                    "organization_id": (
                        str(user.primary_org_id) if user.primary_org_id else None
                    ),
                },
            )
    except Exception:
        # Never leave a sign-in without its profile behind.
        try:
            await auth.admin_delete_user(user_id=str(new_id))
        except Exception:
            log.error("responder_rollback_failed", user_id=str(new_id), exc_info=True)
        raise

    log.info(
        "responder_created",
        coordinator_id=str(user.id),
        responder_id=str(new_id),
        agency=agency,
    )
    return ResponderCredentials(
        responder=TeamResponder.model_validate(dict(row)),
        email=email,
        temporary_password=password,
    )


# --------------------------------------------------------------------------- #
# Look after
# --------------------------------------------------------------------------- #
@router.post(
    "/responders/{responder_id}/reset-password",
    response_model=ResponderCredentials,
    summary="Give a responder a new temporary password (coordinator)",
)
async def reset_password(
    responder_id: UUID,
    request: Request,
    user: SubAdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> ResponderCredentials:
    """A new temporary password, returned once. The old one stops working."""
    responder = await _responder(db, user, responder_id)
    if not responder.is_active:
        raise ConflictError("Reactivate this account before giving it a new password.")
    password = temporary_password()
    await auth.admin_update_user(user_id=str(responder_id), attributes={"password": password})
    await record_audit(
        db,
        request,
        user,
        action="user.responder_password_reset",
        entity_type="user",
        entity_id=responder_id,
    )
    log.info(
        "responder_password_reset",
        coordinator_id=str(user.id),
        responder_id=str(responder_id),
    )
    return ResponderCredentials(
        responder=responder, email=responder.email, temporary_password=password
    )


@router.post(
    "/responders/{responder_id}/deactivate",
    response_model=TeamResponder,
    summary="Stop a responder account signing in (coordinator)",
)
async def deactivate_responder(
    responder_id: UUID,
    request: Request,
    user: SubAdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> TeamResponder:
    """Deactivate: the history stays, sign-in stops, a live response is released."""
    responder = await _responder(db, user, responder_id)
    if not responder.is_active:
        return responder
    # Supabase first: if the ban fails nothing has changed, and the account is
    # not left marked inactive while it can still make sessions.
    await auth.admin_update_user(
        user_id=str(responder_id), attributes={"ban_duration": _BAN_FOREVER}
    )
    async with db.acquire() as conn, conn.transaction():
        released = await conn.fetch(
            """
            update public.dispatch_logs
               set status = 'withdrawn', withdrawn_at = now()
             where responder_id = $1 and status = 'active'
             returning area_id
            """,
            responder_id,
        )
        await conn.execute(
            "update public.device_tokens set is_active = false where user_id = $1",
            responder_id,
        )
        await conn.execute(
            """
            update public.users
               set is_active = false, deactivated_at = now(), deactivated_by = $2,
                   updated_at = now()
             where id = $1
            """,
            responder_id,
            user.id,
        )
        await record_audit(
            conn,
            request,
            user,
            action="user.responder_deactivated",
            entity_type="user",
            entity_id=responder_id,
            metadata={"responses_released": [str(r["area_id"]) for r in released]},
        )
    log.info(
        "responder_deactivated",
        coordinator_id=str(user.id),
        responder_id=str(responder_id),
        responses_released=len(released),
    )
    return await _responder(db, user, responder_id)


@router.post(
    "/responders/{responder_id}/reactivate",
    response_model=TeamResponder,
    summary="Let a deactivated responder sign in again (coordinator)",
)
async def reactivate_responder(
    responder_id: UUID,
    request: Request,
    user: SubAdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> TeamResponder:
    """Lift the ban. Their old password works again; reset it if it was lost."""
    responder = await _responder(db, user, responder_id)
    if responder.is_active:
        return responder
    await auth.admin_update_user(user_id=str(responder_id), attributes={"ban_duration": "none"})
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            update public.users
               set is_active = true, deactivated_at = null, deactivated_by = null,
                   updated_at = now()
             where id = $1
            """,
            responder_id,
        )
        await record_audit(
            conn,
            request,
            user,
            action="user.responder_reactivated",
            entity_type="user",
            entity_id=responder_id,
        )
    log.info("responder_reactivated", coordinator_id=str(user.id), responder_id=str(responder_id))
    return await _responder(db, user, responder_id)
