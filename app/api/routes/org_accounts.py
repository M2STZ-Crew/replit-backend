"""An Admin's Coordinator accounts (PRD v13/v14 §4.6.4; pass 6 A48, A49, A49b).

Tier 1 creates Tier 2: every organisation's Admin creates the Coordinator
(sub_admin) accounts of its own organisation, and turns them off and on again.
Coordinators then create their Responders on the mobile app (routes/team.py).
The system Admin, which belongs to no organisation, names the organisation.

A new Coordinator gets an email with a link to set their own password, the same
way an accepted affiliate's contact does, so the Admin never handles it. The
console lists the roster from GET /organizations/{id}/personnel.
"""

from __future__ import annotations

import html
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import AuthClientDep, CoordinatorManager, DatabaseDep, EmailClientDep
from app.api.routes.organizations import PERSONNEL_SELECT
from app.api.routes.password_reset import reset_page_url
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
    OrganizationMember,
)
from app.services.access import admin_access
from app.services.audit import record_audit

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
    Admin the one it named."""
    access = admin_access(admin)
    assert access is not None  # CoordinatorManager admits Admins only
    if access.is_system:
        if requested is None:
            raise BadRequestError("Choose the organisation the Coordinator belongs to.")
        return requested
    if requested is not None and requested != access.organization_id:
        raise ForbiddenError("You create Coordinators for your own organisation only.")
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
        or (not access.is_system and row["primary_org_id"] != access.organization_id)
    ):
        raise NotFoundError("No Coordinator of your organisation has that id.")
    return await _member(db, user_id)


def _invite_html(name: str, org_name: str, link: str) -> str:
    name, org_name, link = html.escape(name), html.escape(org_name), html.escape(link)
    return (
        '<div style="font-family:Inter,Arial,sans-serif;color:#111;max-width:520px">'
        f"<h2 style='margin:0 0 12px'>You're a Coordinator for {org_name}</h2>"
        f"<p>Hi {name}, your organisation's Admin made you a Coordinator on RepLiT, "
        "Pasay City's fire reporting and response network.</p>"
        "<p>Set your password, then sign in to the RepLiT mobile app with this email "
        "address. From there you acknowledge incidents and create your Responders' "
        "accounts.</p>"
        f'<p><a href="{link}" style="display:inline-block;background:#EB4800;'
        'color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;'
        'font-weight:bold">Set my password</a></p>'
        '<p style="color:#666;font-size:13px">If the button does not work, copy this '
        f"link into your browser:<br>{link}</p>"
        "</div>"
    )


def _invite_text(name: str, org_name: str, link: str) -> str:
    return (
        f"Hi {name},\n\n"
        f"Your organisation's Admin made you a Coordinator for {org_name} on RepLiT.\n\n"
        "Set your password, then sign in to the RepLiT mobile app with this email "
        f"address:\n{link}\n"
    )


@router.post(
    "",
    response_model=CoordinatorCreateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Coordinator account for my organisation (Admin)",
)
async def create_coordinator(
    payload: CoordinatorCreateRequest,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> CoordinatorCreateResult:
    """A Coordinator of the Admin's organisation, emailed a link to set a password.

    Refuses an email that already has an account, rather than taking it over:
    promoting someone's existing account is not an organisation Admin's call.
    """
    org_id = _target_organization(admin, payload.organization_id)
    org = await db.fetchrow(
        "select id, name, agency_type::text as agency_type, is_active "
        "from public.organizations where id = $1",
        org_id,
    )
    if org is None:
        raise NotFoundError("Organisation not found.")
    if not org["is_active"]:
        raise ConflictError("That organisation is not active on RepLiT.")

    email = str(payload.email).strip().lower()
    full_name = payload.full_name.strip()
    title = payload.title.strip() if payload.title and payload.title.strip() else None
    taken = await db.fetchval(
        "select 1 from public.users where lower(email) = $1", email
    )
    if taken:
        raise ConflictError(
            "An account already uses this email. Use another address for the "
            "Coordinator."
        )

    try:
        created: dict[str, Any] = await auth.admin_create_user(
            email=email,
            # Never used: the Coordinator sets their own from the email.
            password=secrets.token_urlsafe(24),
            email_confirm=True,
            user_metadata={"full_name": full_name},
        )
    except (BadRequestError, AuthError) as exc:
        raise ConflictError(
            "That email could not be used for a new account. Use another address."
        ) from exc
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
                       is_active = true,
                       updated_at = now()
                 where id = $1
                """,
                new_id,
                org["agency_type"],
                org_id,
                full_name,
                admin.id,
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
                    "role": "sub_admin",
                    "agency": org["agency_type"],
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
        link_resp = await auth.admin_generate_link(
            link_type="recovery", email=email, redirect_to=reset_page_url()
        )
        action_link = link_resp.get("action_link") or (
            link_resp.get("properties") or {}
        ).get("action_link")
        if isinstance(action_link, str) and action_link:
            await email_client.send(
                to=email,
                subject=f"You're a Coordinator for {org['name']} on RepLiT",
                html=_invite_html(full_name, org["name"], action_link),
                text=_invite_text(full_name, org["name"], action_link),
            )
            sent = True
        else:
            detail = "The account is ready, but no password link was generated."
    except AppError as exc:
        detail = (
            "The account is ready, but the email with the password link could not be "
            "sent. They can use “Forgot password?” on the app with this email."
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
        coordinator=await _member(db, new_id), invite_email_sent=sent, detail=detail
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
