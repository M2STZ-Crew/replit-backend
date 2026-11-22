"""An Admin's staff accounts: Coordinators and Responders, managed the same way.

v1.12.49 gave Admins full control of Responders (22 Nov 2026: "admin can
manage responders too"; answered "Full account control" and "Own org; hub
manages all"). v1.12.51 gives them the same for Coordinators (23 Nov 2026:
"make the account management in coordinator and responder the same. they can
do all those managing things in coordinator and responder too that send that
link and things"). One set of rules for both:

* **Every Admin** creates its own organization's accounts, edits their name,
  title and mobile, emails them a password link, turns them off and on, and
  sees who is on a fire.
* **The central hub and the system Admin** do that for everyone, and move one
  to another organization of the same agency. Not while they are on a fire.
* No password passes through the console. The link goes to their own email. An
  Admin fills that in where there is none or it was never confirmed; once
  confirmed, only they change it, from Profile.
* Every change is in the audit log.

The routes are app/api/routes/admin_responders.py and org_accounts.py.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from fastapi import Request

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
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.supabase_auth import SupabaseAuthClient
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import CoordinatorCreateRequest
from app.schemas.team import (
    AdminCoordinator,
    AdminResponder,
    AdminResponderCreate,
    AdminResponderLink,
    AdminResponderUpdate,
)
from app.services import responder_lifecycle as lifecycle
from app.services.access import admin_access
from app.services.audit import record_audit
from app.services.names import clean_name, is_valid_name
from app.services.phone_verification import normalize_ph_mobile
from app.services.responder_accounts import AGENCY_CODES, is_staff_address
from app.services.responder_lifecycle import COORDINATOR, RESPONDER, StaffKind
from app.services.staff_links import RESET_FOR, password_link, reset_email

log = get_logger(__name__)

_MODELS: dict[StaffKind, type[AdminResponder]] = {
    RESPONDER: AdminResponder,
    COORDINATOR: AdminCoordinator,
}

# $1 is the organization whose accounts the caller manages; null is everyone's.
_SELECT = """
    select u.id, u.full_name, u.email, u.mobile, u.agency_type::text as agency_type,
           u.is_active, u.created_at, u.deactivated_at, u.personal_email,
           (u.personal_email_verified_at is not null) as personal_email_verified,
           u.primary_org_id as organization_id, o.name as organization_name,
           rr.title, cb.full_name as created_by_name,
           (live.area_id is not null) as responding,
           live.area_id as responding_area_id,
           live.designation as responding_to,
           live.dispatched_at as responding_since
      from public.users u
      left join public.organizations o on o.id = u.primary_org_id
      left join public.org_roster rr
             on rr.organization_id = u.primary_org_id and rr.user_id = u.id
      left join public.users cb on cb.id = u.created_by
      left join lateral (
            select d.area_id, a.designation, d.dispatched_at
              from public.dispatch_logs d
              join public.areas a on a.id = d.area_id
             where d.responder_id = u.id and d.status = 'active'
             order by d.dispatched_at desc
             limit 1
      ) live on true
     where u.role = '{role}'
       and ($1::uuid is null or u.primary_org_id = $1)
"""


def scope_of(admin: AuthenticatedUser, kind: StaffKind) -> UUID | None:
    """The organization whose accounts this Admin manages; None is everyone's,
    the central hub's and the system Admin's alone."""
    access = admin_access(admin)
    if access is not None and access.governs_all:
        return None
    if access is None or access.organization_id is None:
        raise ForbiddenError(
            f"Your Admin account has no organization to manage {kind.noun}s for."
        )
    return access.organization_id


def made_by(admin: AuthenticatedUser, org_id: UUID | None) -> str:
    """How an email names the Admin who sent it."""
    if org_id is not None and org_id == admin.primary_org_id:
        return "Your organization's Admin"
    return "A RepLiT Admin"


def valid_name(raw: str | None) -> str:
    name = clean_name(raw)
    if name is None or not is_valid_name(name):
        raise BadRequestError(
            "Use letters for their name. Spaces, periods, apostrophes and hyphens are fine.",
            error_code="invalid_name",
            details={"field": "full_name"},
        )
    return name


def _optional(raw: str | None) -> str | None:
    return (raw or "").strip() or None


def _mobile(raw: str | None) -> str | None:
    given = _optional(raw)
    return normalize_ph_mobile(given) if given else None


async def _organization(db: Database, org_id: UUID, kind: StaffKind) -> Any:
    """An organization these accounts can be in: live, with staff addresses."""
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
        raise BadRequestError(f"This organization's agency has no {kind.word} accounts.")
    return org


def _target(admin: AuthenticatedUser, requested: UUID | None, kind: StaffKind) -> UUID:
    """The organization a new account joins."""
    scope = scope_of(admin, kind)
    if scope is not None:
        if requested is not None and requested != scope:
            raise ForbiddenError(f"You create {kind.noun}s for your own organization only.")
        return scope
    target = requested or admin.primary_org_id
    if target is None:
        raise BadRequestError(f"Choose the organization the {kind.noun} belongs to.")
    return target


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def one(
    db: Database, admin: AuthenticatedUser, user_id: UUID, kind: StaffKind
) -> AdminResponder:
    """One account this Admin manages, or 404: another organization's is not
    found rather than refused, so ids cannot be probed."""
    row = await db.fetchrow(
        f"{_SELECT.format(role=kind.role)} and u.id = $2", scope_of(admin, kind), user_id
    )
    if row is None:
        raise NotFoundError(f"No {kind.noun} of yours has that id.")
    return _MODELS[kind].model_validate(dict(row))


async def everyone(
    db: Database, admin: AuthenticatedUser, kind: StaffKind
) -> list[AdminResponder]:
    """Who is on a fire first, then who can sign in, then by name."""
    rows = await db.fetch(
        f"{_SELECT.format(role=kind.role)} "
        "order by (live.area_id is not null) desc, u.is_active desc, "
        "u.full_name nulls last, u.email",
        scope_of(admin, kind),
    )
    return [_MODELS[kind].model_validate(dict(r)) for r in rows]


async def preview_address(
    db: Database,
    admin: AuthenticatedUser,
    kind: StaffKind,
    *,
    first: str,
    last: str,
    organization_id: UUID | None,
) -> str:
    org = await _organization(db, _target(admin, organization_id, kind), kind)
    return await lifecycle.next_address(db, first, last, org["agency_type"], kind)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
async def create(
    db: Database,
    auth: SupabaseAuthClient,
    email_client: BrevoEmailClient,
    request: Request | None,
    admin: AuthenticatedUser,
    payload: AdminResponderCreate | CoordinatorCreateRequest,
    kind: StaffKind,
) -> tuple[AdminResponder, bool, str | None]:
    """An account of the organization's agency, emailed a link to set a
    password: the account, whether the email went, and why not."""
    org_id = _target(admin, payload.organization_id, kind)
    first = payload.first_name.strip()
    last = payload.last_name.strip()
    full_name = valid_name(f"{first} {last}")
    title = _optional(payload.title)
    mobile = _mobile(payload.mobile)
    personal = lifecycle.own_email(str(payload.personal_email), kind)
    assert personal is not None  # the schemas require one
    org = await _organization(db, org_id, kind)
    agency = org["agency_type"]
    new_id, address = await lifecycle.make_sign_in(
        db,
        auth,
        first=first,
        last=last,
        agency=agency,
        # Never used: they set their own from the email.
        password=secrets.token_urlsafe(24),
        kind=kind,
    )
    try:
        async with db.acquire() as conn, conn.transaction():
            await lifecycle.write_profile(
                conn,
                kind,
                new_id,
                agency=agency,
                org_id=org_id,
                full_name=full_name,
                mobile=mobile,
                created_by=admin.id,
                personal=personal,
            )
            await lifecycle.put_on_roster(conn, kind, org_id, new_id, title)
            await record_audit(
                conn,
                request,
                admin,
                action=f"user.{kind.key}_created",
                entity_type="user",
                entity_id=new_id,
                after_state={
                    "email": address,
                    "personal_email": personal,
                    "role": kind.role,
                    "agency": agency,
                    "organization_id": str(org_id),
                    "title": title,
                    "mobile": mobile,
                },
                metadata={kind.key: full_name},
            )
    except Exception:
        await lifecycle.discard_sign_in(auth, new_id)
        raise

    sent, detail = await lifecycle.send_welcome(
        email_client,
        user_id=new_id,
        name=full_name,
        organization=str(org["name"]),
        address=address,
        personal=personal,
        made_by=made_by(admin, org_id),
        kind=kind,
    )
    log.info(
        "admin_staff_created",
        kind=kind.key,
        admin_id=str(admin.id),
        account_id=str(new_id),
        organization_id=str(org_id),
        invite_email_sent=sent,
    )
    return await one(db, admin, new_id, kind), sent, detail


# --------------------------------------------------------------------------- #
# Edit and move
# --------------------------------------------------------------------------- #
async def update(
    db: Database,
    request: Request | None,
    admin: AuthenticatedUser,
    user_id: UUID,
    payload: AdminResponderUpdate,
    kind: StaffKind,
) -> AdminResponder:
    """Only what is sent changes; an empty title or mobile clears it."""
    scope = scope_of(admin, kind)
    sent = payload.model_fields_set
    if "organization_id" in sent:
        if payload.organization_id is None:
            raise BadRequestError("Choose the organization to move them to.")
        if scope is not None and payload.organization_id != scope:
            raise ForbiddenError(
                f"Only the central hub moves a {kind.noun} to another organization."
            )
    changes: dict[str, Any] = {}
    if "full_name" in sent:
        changes["full_name"] = valid_name(payload.full_name)
    if "mobile" in sent:
        changes["mobile"] = _mobile(payload.mobile)
    if "title" in sent:
        changes["title"] = _optional(payload.title)
    org: Any = (
        await _organization(db, payload.organization_id, kind)
        if payload.organization_id
        else None
    )

    async with db.acquire() as conn, conn.transaction():
        # Locked, so a dispatch cannot land between the check and a move.
        was = await conn.fetchrow(
            f"""
            select u.full_name, u.mobile, u.agency_type::text as agency_type,
                   u.primary_org_id as organization_id, o.name as organization_name
              from public.users u
              left join public.organizations o on o.id = u.primary_org_id
             where u.id = $1 and u.role = '{kind.role}'
               and ($2::uuid is null or u.primary_org_id = $2)
               for update of u
            """,
            user_id,
            scope,
        )
        if was is None:
            raise NotFoundError(f"No {kind.noun} of yours has that id.")
        old_org = was["organization_id"]
        title = None
        if old_org is not None:
            title = await conn.fetchval(
                "select title from public.org_roster where organization_id = $1 and user_id = $2",
                old_org,
                user_id,
            )
        before = {"full_name": was["full_name"], "mobile": was["mobile"], "title": title}
        after = {**before, **changes}
        moved = org is not None and org["id"] != old_org
        if moved:
            if org["agency_type"] != was["agency_type"]:
                raise ConflictError(
                    f"A {kind.noun} moves only to an organization of the same agency.",
                    error_code="other_agency",
                )
            on_a_fire = await conn.fetchval(
                "select exists (select 1 from public.dispatch_logs "
                "where responder_id = $1 and status = 'active')",
                user_id,
            )
            if on_a_fire:
                raise ConflictError(
                    "They are on a fire. Move them once their response ends.",
                    error_code="responding",
                )
        new_org = org["id"] if moved else old_org
        if after["title"] and new_org is None:
            raise BadRequestError("Move them to an organization before giving them a title.")
        changed = [key for key in before if before[key] != after[key]]
        if changed or moved:
            await conn.execute(
                """
                update public.users
                   set full_name = $2, mobile = $3, primary_org_id = $4, updated_at = now()
                 where id = $1
                """,
                user_id,
                after["full_name"],
                after["mobile"],
                new_org,
            )
            if moved and old_org is not None:
                await conn.execute(
                    "update public.org_roster set is_active = false, updated_at = now() "
                    "where organization_id = $1 and user_id = $2",
                    old_org,
                    user_id,
                )
            if new_org is not None and (moved or "title" in changed):
                await lifecycle.put_on_roster(conn, kind, new_org, user_id, after["title"])
            before_state = {key: before[key] for key in changed}
            after_state = {key: after[key] for key in changed}
            if moved:
                before_state["organization"] = was["organization_name"]
                after_state["organization"] = org["name"]
            await record_audit(
                conn,
                request,
                admin,
                action=f"user.{kind.key}_{'moved' if moved else 'updated'}",
                entity_type="user",
                entity_id=user_id,
                before_state=before_state,
                after_state=after_state,
                metadata={
                    kind.key: after["full_name"],
                    "changed": changed,
                    "moved_to": org["name"] if moved else None,
                },
            )
            log.info(
                "admin_staff_updated",
                kind=kind.key,
                admin_id=str(admin.id),
                account_id=str(user_id),
                changed=changed,
                moved=moved,
            )
    return await one(db, admin, user_id, kind)


# --------------------------------------------------------------------------- #
# Password link
# --------------------------------------------------------------------------- #
async def send_link(
    db: Database,
    auth: SupabaseAuthClient,
    email_client: BrevoEmailClient,
    request: Request | None,
    admin: AuthenticatedUser,
    user_id: UUID,
    payload: AdminResponderLink,
    kind: StaffKind,
    *,
    redirect_to: str,
) -> str:
    """Email a link to set a password: where it went. Their current password
    works until they set another from it."""
    who = await one(db, admin, user_id, kind)
    if not who.is_active:
        raise ConflictError("Turn this account on before sending a password link.")
    given = lifecycle.own_email(
        str(payload.personal_email) if payload.personal_email else None, kind
    )
    current = (who.personal_email or "").strip().lower() or None

    if is_staff_address(who.email):
        to = given or current
        if to is None:
            raise BadRequestError(
                f"Enter the {kind.noun}'s own email. The link goes there.",
                error_code="personal_email_needed",
            )
        if to != current:
            async with db.acquire() as conn, conn.transaction():
                # A confirmed email is theirs to change.
                done = await conn.execute(
                    """
                    update public.users
                       set personal_email = $2, updated_at = now()
                     where id = $1 and personal_email_verified_at is null
                    """,
                    user_id,
                    to,
                )
                if done.endswith(" 0"):
                    raise ConflictError(
                        "They confirmed their email. Only they can change it, in Profile.",
                        error_code="personal_email_confirmed",
                    )
                await record_audit(
                    conn,
                    request,
                    admin,
                    action=f"user.{kind.key}_email_set",
                    entity_type="user",
                    entity_id=user_id,
                    before_state={"personal_email": current},
                    after_state={"personal_email": to},
                    metadata={kind.key: who.full_name},
                )
        link: Any = password_link(user_id, to, RESET_FOR)
    else:
        # An account from before made addresses signs in with a real mailbox.
        to = who.email
        if given and given != to.lower():
            raise ConflictError(
                "The link goes to the email they sign in with.",
                error_code="sign_in_is_mailbox",
            )
        made = await auth.admin_generate_link(
            link_type="recovery", email=to, redirect_to=redirect_to
        )
        link = made.get("action_link") or (made.get("properties") or {}).get("action_link")
        if not isinstance(link, str) or not link:
            raise ExternalServiceError("The password link could not be made. Try again.")

    message = reset_email(
        address=who.email, link=link, sent_by=made_by(admin, who.organization_id)
    )
    try:
        await email_client.send(
            to=to, subject="Set your RepLiT password", html=message.html, text=message.text
        )
    except AppError as exc:
        log.warning(
            "admin_staff_link_failed", kind=kind.key, account_id=str(user_id), error=str(exc)
        )
        raise ExternalServiceError(
            f"The email to {to} could not be sent. Try again in a minute."
        ) from exc
    await record_audit(
        db,
        request,
        admin,
        action=f"user.{kind.key}_password_link",
        entity_type="user",
        entity_id=user_id,
        metadata={kind.key: who.full_name},
    )
    log.info(
        "admin_staff_link_sent", kind=kind.key, admin_id=str(admin.id), account_id=str(user_id)
    )
    return to


# --------------------------------------------------------------------------- #
# Off and on
# --------------------------------------------------------------------------- #
async def deactivate(
    db: Database,
    auth: SupabaseAuthClient,
    request: Request | None,
    admin: AuthenticatedUser,
    user_id: UUID,
    kind: StaffKind,
) -> AdminResponder:
    """Turn off: sign-in stops and a live response is released."""
    who = await one(db, admin, user_id, kind)
    if not who.is_active:
        return who
    released = await lifecycle.turn_off(
        db, auth, request, admin, user_id, name=who.full_name, kind=kind
    )
    log.info(
        "admin_staff_deactivated",
        kind=kind.key,
        admin_id=str(admin.id),
        account_id=str(user_id),
        responses_released=len(released),
    )
    return await one(db, admin, user_id, kind)


async def reactivate(
    db: Database,
    auth: SupabaseAuthClient,
    request: Request | None,
    admin: AuthenticatedUser,
    user_id: UUID,
    kind: StaffKind,
) -> AdminResponder:
    """Their old password works again."""
    who = await one(db, admin, user_id, kind)
    if who.is_active:
        return who
    await lifecycle.turn_on(db, auth, request, admin, user_id, name=who.full_name, kind=kind)
    log.info(
        "admin_staff_reactivated",
        kind=kind.key,
        admin_id=str(admin.id),
        account_id=str(user_id),
    )
    return await one(db, admin, user_id, kind)
