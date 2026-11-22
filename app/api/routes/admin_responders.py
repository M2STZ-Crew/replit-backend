"""An Admin's responder accounts (v1.12.49; 22 Nov 2026: "admin can manage
responders too (because they are the most powerful)").

Answered "Full account control" and "Own org; hub manages all":

* **Every Admin** creates its own organization's responders, edits their name,
  title and mobile, emails them a password link, turns them off and on, and
  sees who is on a fire.
* **The central hub and the system Admin** do that for everyone, responders
  with no organization included, and move one to another organization of the
  same agency. Not while they are on a fire: the response is their team's.
* Dispatching stays with coordinators, who keep managing their own teams
  (app/api/routes/team.py). Every change is in the audit log.

No password passes through the console. The link goes to the responder's own
email. An Admin fills that in where there is none or it was never confirmed;
once confirmed, only the responder changes it, from Profile.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, DatabaseDep, EmailClientDep, ResponderManager
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
from app.schemas.auth import AuthenticatedUser
from app.schemas.team import (
    AdminResponder,
    AdminResponderCreate,
    AdminResponderCreated,
    AdminResponderLink,
    AdminResponderLinkSent,
    AdminResponderUpdate,
    ResponderEmailPreview,
)
from app.services import responder_lifecycle as lifecycle
from app.services.access import admin_access
from app.services.audit import record_audit
from app.services.names import clean_name, is_valid_name
from app.services.phone_verification import normalize_ph_mobile
from app.services.responder_accounts import AGENCY_CODES, is_staff_address
from app.services.staff_links import RESET_FOR, password_link, reset_email

log = get_logger(__name__)

router = APIRouter(prefix="/admin/responders", tags=["admin"])

# $1 is the organization whose responders the caller manages; null is everyone's.
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
     where u.role = 'response_team'
       and ($1::uuid is null or u.primary_org_id = $1)
"""


def _scope(admin: AuthenticatedUser) -> UUID | None:
    """The organization whose responders this Admin manages; None is everyone's,
    the central hub's and the system Admin's alone."""
    access = admin_access(admin)
    if access is not None and access.governs_all:
        return None
    if access is None or access.organization_id is None:
        raise ForbiddenError("Your Admin account has no organization to manage responders for.")
    return access.organization_id


def _made_by(admin: AuthenticatedUser, org_id: UUID | None) -> str:
    """How an email names the Admin who sent it."""
    if org_id is not None and org_id == admin.primary_org_id:
        return "Your organization's Admin"
    return "A RepLiT Admin"


async def _responder(db: Database, admin: AuthenticatedUser, user_id: UUID) -> AdminResponder:
    """One responder this Admin manages, or 404: another organization's is not
    found rather than refused, so ids cannot be probed."""
    row = await db.fetchrow(f"{_SELECT} and u.id = $2", _scope(admin), user_id)
    if row is None:
        raise NotFoundError("No responder of yours has that id.")
    return AdminResponder.model_validate(dict(row))


async def _organization(db: Database, org_id: UUID) -> Any:
    """An organization responders can be in: live, with staff addresses."""
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
        raise BadRequestError("This organization's agency has no Responder accounts.")
    return org


def _target(admin: AuthenticatedUser, requested: UUID | None) -> UUID:
    """The organization a new responder joins."""
    scope = _scope(admin)
    if scope is not None:
        if requested is not None and requested != scope:
            raise ForbiddenError("You create responders for your own organization only.")
        return scope
    target = requested or admin.primary_org_id
    if target is None:
        raise BadRequestError("Choose the organization the responder belongs to.")
    return target


def _name(raw: str | None) -> str:
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


async def _put_on_roster(conn: Any, org_id: UUID, user_id: UUID, title: str | None) -> None:
    await conn.execute(
        """
        insert into public.org_roster (organization_id, user_id, member_role, title)
        values ($1, $2, 'response_team', $3)
        on conflict (organization_id, user_id) do update
           set member_role = excluded.member_role, title = excluded.title,
               is_active = true, updated_at = now()
        """,
        org_id,
        user_id,
        title,
    )


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[AdminResponder], summary="The responders I manage (Admin)")
async def list_responders(admin: ResponderManager, db: DatabaseDep) -> list[AdminResponder]:
    """Who is on a fire first, then who can sign in, then by name."""
    rows = await db.fetch(
        f"{_SELECT} order by (live.area_id is not null) desc, u.is_active desc, "
        "u.full_name nulls last, u.email",
        _scope(admin),
    )
    return [AdminResponder.model_validate(dict(r)) for r in rows]


@router.get(
    "/email-preview",
    response_model=ResponderEmailPreview,
    summary="The address a new responder with this name would get (Admin)",
)
async def preview_responder_email(
    admin: ResponderManager,
    db: DatabaseDep,
    first_name: str = Query(min_length=1, max_length=60),
    last_name: str = Query(min_length=1, max_length=60),
    organization_id: Annotated[UUID | None, Query()] = None,
) -> ResponderEmailPreview:
    """Shown on the form as the name is typed; the create takes the next free one."""
    org = await _organization(db, _target(admin, organization_id))
    return ResponderEmailPreview(
        email=await lifecycle.next_address(db, first_name, last_name, org["agency_type"])
    )


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@router.post(
    "",
    response_model=AdminResponderCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a responder account (Admin)",
)
async def create_responder(
    payload: AdminResponderCreate,
    request: Request,
    admin: ResponderManager,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> AdminResponderCreated:
    """A responder of the organization's agency, emailed a link to set a password."""
    org_id = _target(admin, payload.organization_id)
    first = payload.first_name.strip()
    last = payload.last_name.strip()
    full_name = _name(f"{first} {last}")
    title = _optional(payload.title)
    mobile = _mobile(payload.mobile)
    personal = lifecycle.own_email(str(payload.personal_email))
    assert personal is not None  # the schema requires one
    org = await _organization(db, org_id)
    agency = org["agency_type"]
    new_id, address = await lifecycle.make_sign_in(
        db,
        auth,
        first=first,
        last=last,
        agency=agency,
        # Never used: the responder sets their own from the email.
        password=secrets.token_urlsafe(24),
    )
    try:
        async with db.acquire() as conn, conn.transaction():
            updated = await conn.execute(
                """
                update public.users
                   set role = 'response_team',
                       agency_type = $2::public.agency_type,
                       primary_org_id = $3,
                       full_name = $4,
                       mobile = $5,
                       created_by = $6,
                       personal_email = $7,
                       personal_email_verified_at = null,
                       is_active = true,
                       updated_at = now()
                 where id = $1
                """,
                new_id,
                agency,
                org_id,
                full_name,
                mobile,
                admin.id,
                personal,
            )
            if updated.endswith(" 0"):
                raise ExternalServiceError("Account created but its profile was not found.")
            await _put_on_roster(conn, org_id, new_id, title)
            await record_audit(
                conn,
                request,
                admin,
                action="user.responder_created",
                entity_type="user",
                entity_id=new_id,
                after_state={
                    "email": address,
                    "personal_email": personal,
                    "role": "response_team",
                    "agency": agency,
                    "organization_id": str(org_id),
                    "title": title,
                    "mobile": mobile,
                },
                metadata={"responder": full_name},
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
        made_by=_made_by(admin, org_id),
    )
    log.info(
        "admin_responder_created",
        admin_id=str(admin.id),
        responder_id=str(new_id),
        organization_id=str(org_id),
        invite_email_sent=sent,
    )
    return AdminResponderCreated(
        responder=await _responder(db, admin, new_id),
        invite_email_sent=sent,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Edit and move
# --------------------------------------------------------------------------- #
@router.patch(
    "/{user_id}",
    response_model=AdminResponder,
    summary="Edit a responder, or move one to another organization (Admin)",
)
async def update_responder(
    user_id: UUID,
    payload: AdminResponderUpdate,
    request: Request,
    admin: ResponderManager,
    db: DatabaseDep,
) -> AdminResponder:
    """Only what is sent changes; an empty title or mobile clears it."""
    scope = _scope(admin)
    sent = payload.model_fields_set
    if "organization_id" in sent:
        if payload.organization_id is None:
            raise BadRequestError("Choose the organization to move them to.")
        if scope is not None and payload.organization_id != scope:
            raise ForbiddenError("Only the central hub moves a responder to another organization.")
    changes: dict[str, Any] = {}
    if "full_name" in sent:
        changes["full_name"] = _name(payload.full_name)
    if "mobile" in sent:
        changes["mobile"] = _mobile(payload.mobile)
    if "title" in sent:
        changes["title"] = _optional(payload.title)
    org = await _organization(db, payload.organization_id) if payload.organization_id else None

    async with db.acquire() as conn, conn.transaction():
        # Locked, so a dispatch cannot land between the check and a move.
        was = await conn.fetchrow(
            """
            select u.full_name, u.mobile, u.agency_type::text as agency_type,
                   u.primary_org_id as organization_id, o.name as organization_name
              from public.users u
              left join public.organizations o on o.id = u.primary_org_id
             where u.id = $1 and u.role = 'response_team'
               and ($2::uuid is null or u.primary_org_id = $2)
               for update of u
            """,
            user_id,
            scope,
        )
        if was is None:
            raise NotFoundError("No responder of yours has that id.")
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
                    "A responder moves only to an organization of the same agency.",
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
                await _put_on_roster(conn, new_org, user_id, after["title"])
            before_state = {key: before[key] for key in changed}
            after_state = {key: after[key] for key in changed}
            if moved:
                before_state["organization"] = was["organization_name"]
                after_state["organization"] = org["name"]
            await record_audit(
                conn,
                request,
                admin,
                action="user.responder_moved" if moved else "user.responder_updated",
                entity_type="user",
                entity_id=user_id,
                before_state=before_state,
                after_state=after_state,
                metadata={
                    "responder": after["full_name"],
                    "changed": changed,
                    "moved_to": org["name"] if moved else None,
                },
            )
            log.info(
                "admin_responder_updated",
                admin_id=str(admin.id),
                responder_id=str(user_id),
                changed=changed,
                moved=moved,
            )
    return await _responder(db, admin, user_id)


# --------------------------------------------------------------------------- #
# Password link
# --------------------------------------------------------------------------- #
@router.post(
    "/{user_id}/password-link",
    response_model=AdminResponderLinkSent,
    summary="Email a responder a link to set a password (Admin)",
)
async def send_password_link(
    user_id: UUID,
    payload: AdminResponderLink,
    request: Request,
    admin: ResponderManager,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> AdminResponderLinkSent:
    """Their current password works until they set another from the link."""
    who = await _responder(db, admin, user_id)
    if not who.is_active:
        raise ConflictError("Turn this account on before sending a password link.")
    given = lifecycle.own_email(str(payload.personal_email) if payload.personal_email else None)
    current = (who.personal_email or "").strip().lower() or None

    if is_staff_address(who.email):
        to = given or current
        if to is None:
            raise BadRequestError(
                "Enter the responder's own email. The link goes there.",
                error_code="personal_email_needed",
            )
        if to != current:
            async with db.acquire() as conn, conn.transaction():
                # A confirmed email is the responder's to change.
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
                    action="user.responder_email_set",
                    entity_type="user",
                    entity_id=user_id,
                    before_state={"personal_email": current},
                    after_state={"personal_email": to},
                    metadata={"responder": who.full_name},
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
            link_type="recovery", email=to, redirect_to=reset_page_url()
        )
        link = made.get("action_link") or (made.get("properties") or {}).get("action_link")
        if not isinstance(link, str) or not link:
            raise ExternalServiceError("The password link could not be made. Try again.")

    message = reset_email(
        address=who.email, link=link, sent_by=_made_by(admin, who.organization_id)
    )
    try:
        await email_client.send(
            to=to, subject="Set your RepLiT password", html=message.html, text=message.text
        )
    except AppError as exc:
        log.warning("responder_link_failed", responder_id=str(user_id), error=str(exc))
        raise ExternalServiceError(
            f"The email to {to} could not be sent. Try again in a minute."
        ) from exc
    await record_audit(
        db,
        request,
        admin,
        action="user.responder_password_link",
        entity_type="user",
        entity_id=user_id,
        metadata={"responder": who.full_name},
    )
    log.info("admin_responder_link_sent", admin_id=str(admin.id), responder_id=str(user_id))
    return AdminResponderLinkSent(sent_to=to)


# --------------------------------------------------------------------------- #
# Off and on
# --------------------------------------------------------------------------- #
@router.post(
    "/{user_id}/deactivate",
    response_model=AdminResponder,
    summary="Turn off a responder account (Admin)",
)
async def deactivate_responder(
    user_id: UUID,
    request: Request,
    admin: ResponderManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> AdminResponder:
    """Turn off: sign-in stops and a live response is released."""
    who = await _responder(db, admin, user_id)
    if not who.is_active:
        return who
    released = await lifecycle.turn_off(db, auth, request, admin, user_id, name=who.full_name)
    log.info(
        "admin_responder_deactivated",
        admin_id=str(admin.id),
        responder_id=str(user_id),
        responses_released=len(released),
    )
    return await _responder(db, admin, user_id)


@router.post(
    "/{user_id}/reactivate",
    response_model=AdminResponder,
    summary="Turn a responder account back on (Admin)",
)
async def reactivate_responder(
    user_id: UUID,
    request: Request,
    admin: ResponderManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> AdminResponder:
    """Their old password works again."""
    who = await _responder(db, admin, user_id)
    if who.is_active:
        return who
    await lifecycle.turn_on(db, auth, request, admin, user_id, name=who.full_name)
    log.info("admin_responder_reactivated", admin_id=str(admin.id), responder_id=str(user_id))
    return await _responder(db, admin, user_id)
