"""An Admin's Coordinator accounts (PRD v13/v14 §4.6.4; pass 6 A48, A49, A49b).

Tier 1 creates Tier 2: every organisation's Admin creates the Coordinator
(sub_admin) accounts of its own organisation, and turns them off and on again.
Coordinators then create their Responders on the mobile app (routes/team.py).
The system Admin, which belongs to no organisation, names the organisation.

A new Coordinator signs in with an address made from their name, agency and
role (obryan.fircor@replit.com, the 6 November list). @replit.com has no
mailboxes, so the Admin gives their own email too: a link there confirms it and
sets their password, and later password resets go there as well
(app/services/staff_links.py). The Admin never handles a password. The console
lists the roster from GET /organizations/{id}/personnel.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, CoordinatorManager, DatabaseDep, EmailClientDep
from app.api.routes.organizations import PERSONNEL_SELECT
from app.core.exceptions import (
    AppError,
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.supabase_auth import AuthError
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import (
    CoordinatorCreateRequest,
    CoordinatorCreateResult,
    CoordinatorEmailPreview,
    OrganizationMember,
)
from app.services.access import admin_access
from app.services.audit import record_audit
from app.services.disposable_email import ensure_not_disposable
from app.services.responder_accounts import (
    AGENCY_CODES,
    InvalidNameError,
    is_staff_address,
    staff_email,
    staff_like_pattern,
)
from app.services.staff_links import WELCOME_FOR, password_link, welcome_email

log = get_logger(__name__)

router = APIRouter(prefix="/admin/coordinators", tags=["admin"])

# Supabase Auth's "banned until": a hundred years, as for responders.
_BAN_FOREVER = "876000h"


async def _member(db: Database, user_id: UUID) -> OrganizationMember:
    row = await db.fetchrow(f"{PERSONNEL_SELECT} where u.id = $1", user_id)
    if row is None:
        raise NotFoundError("Account not found.")
    return OrganizationMember.model_validate(dict(row))


def _target_organization(admin: AuthenticatedUser, requested: UUID | None) -> UUID:
    """The organisation this Admin creates into: its own, or for the system
    Admin and the central hub the one it named (the hub's own when it names
    none)."""
    access = admin_access(admin)
    assert access is not None  # CoordinatorManager admits Admins only
    if access.governs_all:
        if requested is not None:
            return requested
        if access.organization_id is None:
            raise BadRequestError("Choose the organization the Coordinator belongs to.")
        return access.organization_id
    if requested is not None and requested != access.organization_id:
        raise ForbiddenError("You create Coordinators for your own organization only.")
    assert access.organization_id is not None
    return access.organization_id


async def _own_coordinator(
    db: Database, admin: AuthenticatedUser, user_id: UUID
) -> OrganizationMember:
    """A Coordinator this Admin looks after, or 404 — another organisation's is
    not found, rather than refused, so ids cannot be probed."""
    access = admin_access(admin)
    assert access is not None
    row = await db.fetchrow(
        "select role::text as role, primary_org_id from public.users where id = $1", user_id
    )
    if (
        row is None
        or row["role"] != "sub_admin"
        or (not access.governs_all and row["primary_org_id"] != access.organization_id)
    ):
        raise NotFoundError("No Coordinator of your organization has that id.")
    return await _member(db, user_id)


async def _organization(db: Database, org_id: UUID) -> Any:
    """The organisation a Coordinator is made for: live, with an agency that has
    staff addresses."""
    org = await db.fetchrow(
        "select id, name, agency_type::text as agency_type, is_active "
        "from public.organizations where id = $1",
        org_id,
    )
    if org is None:
        raise NotFoundError("Organization not found.")
    if not org["is_active"]:
        raise ConflictError("That organization is not active on RepLiT.")
    if org["agency_type"] not in AGENCY_CODES:
        raise BadRequestError("This organization's agency has no Coordinator accounts.")
    return org


async def _taken(db: Database, first: str, last: str, agency: str) -> list[str]:
    """Every address this Coordinator's could collide with."""
    rows = await db.fetch(
        "select email from public.users where lower(email) like $1",
        staff_like_pattern(first, last, agency, "coordinator"),
    )
    return [str(r["email"]) for r in rows if r["email"]]


@router.get(
    "/email-preview",
    response_model=CoordinatorEmailPreview,
    summary="The address a new Coordinator with this name would get (Admin)",
)
async def preview_coordinator_email(
    admin: CoordinatorManager,
    db: DatabaseDep,
    first_name: str = Query(min_length=1, max_length=60),
    last_name: str = Query(min_length=1, max_length=60),
    organization_id: Annotated[UUID | None, Query()] = None,
) -> CoordinatorEmailPreview:
    """Shown on the form as the name is typed; the create takes the next free one."""
    org = await _organization(db, _target_organization(admin, organization_id))
    try:
        email = staff_email(
            first_name,
            last_name,
            org["agency_type"],
            "coordinator",
            await _taken(db, first_name, last_name, org["agency_type"]),
        )
    except InvalidNameError as exc:
        raise BadRequestError(str(exc)) from exc
    return CoordinatorEmailPreview(email=email)


@router.post(
    "",
    response_model=CoordinatorCreateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Coordinator account for my organization (Admin)",
)
async def create_coordinator(
    payload: CoordinatorCreateRequest,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> CoordinatorCreateResult:
    """A Coordinator of the Admin's organisation, signing in at a made address.

    The address takes the next number when the name is taken, and a second Admin
    making the same name at once gets the next one rather than an error. The
    link to set a password goes to the Coordinator's personal email, so one
    from a throwaway service is refused before anything is looked up.
    """
    ensure_not_disposable(str(payload.personal_email), field="personal_email")
    org_id = _target_organization(admin, payload.organization_id)
    org = await _organization(db, org_id)
    agency = org["agency_type"]
    first = payload.first_name.strip()
    last = payload.last_name.strip()
    full_name = f"{first} {last}"
    personal = str(payload.personal_email).strip().lower()
    if is_staff_address(personal):
        raise BadRequestError(
            "Use the Coordinator's own email: @replit.com addresses have no mailbox.",
            error_code="not_personal",
        )
    title = payload.title.strip() if payload.title and payload.title.strip() else None

    created: dict[str, Any] | None = None
    email = ""
    for attempt in range(3):
        try:
            email = staff_email(
                first, last, agency, "coordinator", await _taken(db, first, last, agency)
            )
        except InvalidNameError as exc:
            raise BadRequestError(str(exc)) from exc
        try:
            created = await auth.admin_create_user(
                email=email,
                # Never used: the Coordinator sets their own from the email.
                password=secrets.token_urlsafe(24),
                email_confirm=True,
                user_metadata={"full_name": full_name},
            )
            break
        except (BadRequestError, AuthError) as exc:
            # Taken between the check and the create: take the next number.
            message = getattr(exc, "message", str(exc))
            if "already" not in str(message).lower() or attempt == 2:
                raise ConflictError(
                    "The account could not be made. Try again in a moment."
                ) from exc
            log.info("coordinator_email_race", email=email)
    assert created is not None
    raw_id = created.get("id") or (created.get("user") or {}).get("id")
    if not isinstance(raw_id, str):
        raise ExternalServiceError("Account created but no id was returned by Supabase Auth.")
    new_id = UUID(raw_id)

    try:
        async with db.acquire() as conn, conn.transaction():
            updated = await conn.execute(
                """
                update public.users
                   set role = 'sub_admin',
                       agency_type = $2::public.agency_type,
                       primary_org_id = $3,
                       full_name = $4,
                       created_by = $5,
                       personal_email = $6,
                       personal_email_verified_at = null,
                       is_active = true,
                       updated_at = now()
                 where id = $1
                """,
                new_id,
                agency,
                org_id,
                full_name,
                admin.id,
                personal,
            )
            if updated.endswith(" 0"):
                raise ExternalServiceError("Account created but its profile was not found.")
            await conn.execute(
                """
                insert into public.org_roster (organization_id, user_id, member_role, title)
                values ($1, $2, 'sub_admin', $3)
                on conflict (organization_id, user_id) do update
                   set member_role = excluded.member_role, title = excluded.title,
                       is_active = true, updated_at = now()
                """,
                org_id,
                new_id,
                title,
            )
            await record_audit(
                conn,
                request,
                admin,
                action="user.coordinator_created",
                entity_type="user",
                entity_id=new_id,
                after_state={
                    "email": email,
                    "personal_email": personal,
                    "role": "sub_admin",
                    "agency": agency,
                    "organization_id": str(org_id),
                    "title": title,
                },
            )
    except Exception:
        # Never leave a sign-in without its profile behind.
        try:
            await auth.admin_delete_user(user_id=str(new_id))
        except Exception:
            log.error("coordinator_rollback_failed", user_id=str(new_id), exc_info=True)
        raise

    sent = False
    detail: str | None = None
    try:
        message = welcome_email(
            name=full_name,
            role="Coordinator",
            organization=org["name"],
            address=email,
            link=password_link(new_id, personal, WELCOME_FOR),
            made_by="Your organization's Admin",
        )
        await email_client.send(
            to=personal,
            subject=f"You're a Coordinator for {org['name']} on RepLiT",
            html=message.html,
            text=message.text,
        )
        sent = True
    except AppError as exc:
        detail = (
            f"The account is ready, but the email to {personal} could not be sent. "
            f"They can use “Forgot password?” on the app with {email} or {personal}."
        )
        log.warning("coordinator_invite_failed", user_id=str(new_id), error=str(exc))

    log.info(
        "coordinator_created",
        admin_id=str(admin.id),
        coordinator_id=str(new_id),
        organization_id=str(org_id),
        invite_email_sent=sent,
    )
    return CoordinatorCreateResult(
        coordinator=await _member(db, new_id),
        personal_email=personal,
        invite_email_sent=sent,
        detail=detail,
    )


@router.post(
    "/{user_id}/deactivate",
    response_model=OrganizationMember,
    summary="Turn off a Coordinator account (Admin)",
)
async def deactivate_coordinator(
    user_id: UUID,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> OrganizationMember:
    """Turn off: the history stays, sign-in stops, a live response is released."""
    coordinator = await _own_coordinator(db, admin, user_id)
    if not coordinator.is_active:
        return coordinator
    # Supabase first: if the ban fails nothing has changed, and the account is
    # not left marked off while it can still make sessions.
    await auth.admin_update_user(user_id=str(user_id), attributes={"ban_duration": _BAN_FOREVER})
    async with db.acquire() as conn, conn.transaction():
        released = await conn.fetch(
            """
            update public.dispatch_logs
               set status = 'withdrawn', withdrawn_at = now()
             where responder_id = $1 and status = 'active'
             returning area_id
            """,
            user_id,
        )
        await conn.execute(
            "update public.device_tokens set is_active = false where user_id = $1", user_id
        )
        await conn.execute(
            """
            update public.users
               set is_active = false, deactivated_at = now(), deactivated_by = $2,
                   updated_at = now()
             where id = $1
            """,
            user_id,
            admin.id,
        )
        await record_audit(
            conn,
            request,
            admin,
            action="user.coordinator_deactivated",
            entity_type="user",
            entity_id=user_id,
            metadata={"responses_released": [str(r["area_id"]) for r in released]},
        )
    log.info("coordinator_deactivated", admin_id=str(admin.id), coordinator_id=str(user_id))
    return await _member(db, user_id)


@router.post(
    "/{user_id}/reactivate",
    response_model=OrganizationMember,
    summary="Turn a Coordinator account back on (Admin)",
)
async def reactivate_coordinator(
    user_id: UUID,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> OrganizationMember:
    """Lift the ban. Their old password works again."""
    coordinator = await _own_coordinator(db, admin, user_id)
    if coordinator.is_active:
        return coordinator
    await auth.admin_update_user(user_id=str(user_id), attributes={"ban_duration": "none"})
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            update public.users
               set is_active = true, deactivated_at = null, deactivated_by = null,
                   updated_at = now()
             where id = $1
            """,
            user_id,
        )
        await record_audit(
            conn,
            request,
            admin,
            action="user.coordinator_reactivated",
            entity_type="user",
            entity_id=user_id,
        )
    log.info("coordinator_reactivated", admin_id=str(admin.id), coordinator_id=str(user_id))
    return await _member(db, user_id)
