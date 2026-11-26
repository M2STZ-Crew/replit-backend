"""An accepted organization sets up its Admin (v1.12.53; REPLIT (MAIN) 10 ·
A07–A12; 26 Nov 2026: answered "One-time Admin link").

Accepting an application emails the contact a link to the console's
/admin-registration page (app/api/routes/affiliates.py). There they choose the
first part of the Admin's sign-in, ``<prefix>.admin@replit.com``. The account
is made like every staff account: a made address with no mailbox, and a link
to the contact's own email that confirms it and sets the password. The link
works for 48 hours, and is used up once the organization has an Admin.

GET  /affiliates/admin-registration?token=          the link's state
GET  /affiliates/admin-registration/check?token=&prefix=   available, taken or not allowed
POST /affiliates/admin-registration                 make the Admin
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, DatabaseDep, EmailClientDep
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.supabase_auth import AuthError
from app.schemas.affiliate import (
    AdminPrefixStatus,
    AdminRegistrationCreate,
    AdminRegistrationDone,
    AdminRegistrationLink,
)
from app.schemas.auth import AuthenticatedUser
from app.services import responder_lifecycle as lifecycle
from app.services.affiliate_links import AffiliateLinkError, read_token
from app.services.audit import record_audit
from app.services.staff_links import WELCOME_FOR, password_link, welcome_email

log = get_logger(__name__)

router = APIRouter(prefix="/affiliates/admin-registration", tags=["affiliates"])

ADMIN_SUFFIX = ".admin@replit.com"

# Letters and digits, hyphens inside: "hercules", "brgy-183".
_PREFIX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
PREFIX_HELP = "3 to 30 letters or numbers; a hyphen may join them."
_RESERVED = frozenset(
    {"admin", "system", "root", "support", "replit", "hub", "central", "bfp", "pnp", "police"}
)


def prefix_allowed(prefix: str) -> bool:
    return bool(_PREFIX.fullmatch(prefix)) and prefix not in _RESERVED


async def _link(db: Database, token: str) -> tuple[Any, Any, bool]:
    """The link, its organization, and whether it already has an Admin."""
    try:
        link = read_token(token, "admin")
    except AffiliateLinkError as exc:
        raise NotFoundError("This link is not valid.") from exc
    org = await db.fetchrow(
        "select id, name, is_active from public.organizations where id = $1", link.subject
    )
    if org is None:
        raise NotFoundError("This link is not valid.")
    used = await db.fetchval(
        "select exists (select 1 from public.users "
        "where primary_org_id = $1 and role::text = 'admin')",
        link.subject,
    )
    return link, org, bool(used)


async def _taken(db: Database, address: str) -> bool:
    return bool(
        await db.fetchval(
            "select exists (select 1 from public.users where lower(email) = lower($1))", address
        )
    )


@router.get("", response_model=AdminRegistrationLink, summary="An Admin registration link's state")
async def link_state(db: DatabaseDep, token: str = Query(max_length=1000)) -> AdminRegistrationLink:
    link, org, used = await _link(db, token)
    state = "used" if used else "expired" if link.expired else "valid"
    return AdminRegistrationLink(
        state=state,
        organization=str(org["name"]),
        expires_at=datetime.fromtimestamp(link.expires_at, UTC),
        suffix=ADMIN_SUFFIX,
        prefix_help=PREFIX_HELP,
    )


@router.get(
    "/check", response_model=AdminPrefixStatus, summary="Whether an Admin sign-in prefix is free"
)
async def check_prefix(
    db: DatabaseDep,
    token: str = Query(max_length=1000),
    prefix: str = Query(max_length=60),
) -> AdminPrefixStatus:
    link, _, used = await _link(db, token)
    if used or link.expired:
        raise ConflictError("This link can no longer be used.", error_code="link_ended")
    wanted = prefix.strip().lower()
    if not prefix_allowed(wanted):
        return AdminPrefixStatus(status="not_allowed")
    taken = await _taken(db, f"{wanted}{ADMIN_SUFFIX}")
    return AdminPrefixStatus(status="taken" if taken else "available")


@router.post(
    "",
    response_model=AdminRegistrationDone,
    status_code=status.HTTP_201_CREATED,
    summary="Set up an accepted organization's Admin",
)
async def create_admin(
    payload: AdminRegistrationCreate,
    request: Request,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> AdminRegistrationDone:
    link, org, used = await _link(db, payload.token)
    if used:
        raise ConflictError(
            "This organization's Admin is already set up.", error_code="link_used"
        )
    if link.expired:
        raise ConflictError("This link has expired.", error_code="link_expired")
    if not org["is_active"]:
        raise ConflictError("This organization is not active on RepLiT.")
    wanted = payload.prefix.strip().lower()
    if not prefix_allowed(wanted):
        raise BadRequestError(PREFIX_HELP, error_code="not_allowed", details={"field": "prefix"})
    address = f"{wanted}{ADMIN_SUFFIX}"
    if await _taken(db, address):
        raise ConflictError("That sign-in is taken. Try another.", error_code="taken")
    personal = link.email
    if not personal:
        raise BadRequestError("This link has no email to send the password link to.")
    name = f"{org['name']} Admin"
    try:
        created = await auth.admin_create_user(
            email=address,
            # Never used: the password is set from the emailed link.
            password=secrets.token_urlsafe(24),
            email_confirm=True,
            user_metadata={"full_name": name},
        )
    except (BadRequestError, AuthError) as exc:
        raise ConflictError("That sign-in is taken. Try another.", error_code="taken") from exc
    raw_id = created.get("id") or (created.get("user") or {}).get("id")
    if not isinstance(raw_id, str):
        raise ConflictError("The account could not be made. Try again in a moment.")
    new_id = UUID(raw_id)
    try:
        async with db.acquire() as conn, conn.transaction():
            # One Admin per link: two people submitting at once wait here.
            await conn.execute(
                "select pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"admin-registration:{link.subject}",
            )
            other = await conn.fetchval(
                "select exists (select 1 from public.users where primary_org_id = $1 "
                "and role::text = 'admin' and id <> $2)",
                link.subject,
                new_id,
            )
            if other:
                raise ConflictError(
                    "This organization's Admin is already set up.", error_code="link_used"
                )
            await conn.execute(
                """
                update public.users
                   set role = 'admin', agency_type = null, primary_org_id = $2,
                       full_name = $3, personal_email = $4,
                       personal_email_verified_at = null, is_active = true,
                       updated_at = now()
                 where id = $1
                """,
                new_id,
                link.subject,
                name,
                personal,
            )
            await record_audit(
                conn,
                request,
                AuthenticatedUser(id=new_id, role="admin", primary_org_id=link.subject),
                action="user.admin_registered",
                entity_type="user",
                entity_id=new_id,
                after_state={"email": address, "personal_email": personal},
                metadata={"organization": org["name"]},
            )
    except Exception:
        await lifecycle.discard_sign_in(auth, new_id)
        raise

    sent = True
    try:
        message = welcome_email(
            name=name,
            role="Admin",
            organization=str(org["name"]),
            address=address,
            link=password_link(new_id, personal, WELCOME_FOR),
            made_by="The RepLiT central hub",
            where=f"the RepLiT Admin console at {get_settings().console_base_url}",
        )
        await email_client.send(
            to=personal,
            subject="Your RepLiT Admin account is ready",
            html=message.html,
            text=message.text,
        )
    except Exception:
        sent = False
        log.warning("admin_registration_email_failed", admin_id=str(new_id))
    log.info("admin_registered", admin_id=str(new_id), organization_id=str(link.subject))
    return AdminRegistrationDone(email=address, sent_to=personal, invite_email_sent=sent)
