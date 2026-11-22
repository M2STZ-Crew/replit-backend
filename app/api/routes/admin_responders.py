"""An Admin's responder accounts (v1.12.49; 22 Nov 2026: "admin can manage
responders too (because they are the most powerful)").

Answered "Full account control" and "Own org; hub manages all". The rules are
app/services/staff_admin.py's, shared since v1.12.51 with the Coordinators'
(org_accounts.py). Dispatching stays with coordinators, who keep managing
their own teams (app/api/routes/team.py).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, DatabaseDep, EmailClientDep, ResponderManager
from app.api.routes.password_reset import reset_page_url
from app.schemas.team import (
    AdminResponder,
    AdminResponderCreate,
    AdminResponderCreated,
    AdminResponderLink,
    AdminResponderLinkSent,
    AdminResponderUpdate,
    ResponderEmailPreview,
)
from app.services import staff_admin
from app.services.responder_lifecycle import RESPONDER

router = APIRouter(prefix="/admin/responders", tags=["admin"])


@router.get("", response_model=list[AdminResponder], summary="The responders I manage (Admin)")
async def list_responders(admin: ResponderManager, db: DatabaseDep) -> list[AdminResponder]:
    """Who is on a fire first, then who can sign in, then by name."""
    return await staff_admin.everyone(db, admin, RESPONDER)


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
    email = await staff_admin.preview_address(
        db, admin, RESPONDER, first=first_name, last=last_name, organization_id=organization_id
    )
    return ResponderEmailPreview(email=email)


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
    responder, sent, detail = await staff_admin.create(
        db, auth, email_client, request, admin, payload, RESPONDER
    )
    return AdminResponderCreated(responder=responder, invite_email_sent=sent, detail=detail)


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
    return await staff_admin.update(db, request, admin, user_id, payload, RESPONDER)


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
    to = await staff_admin.send_link(
        db,
        auth,
        email_client,
        request,
        admin,
        user_id,
        payload,
        RESPONDER,
        redirect_to=reset_page_url(),
    )
    return AdminResponderLinkSent(sent_to=to)


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
    return await staff_admin.deactivate(db, auth, request, admin, user_id, RESPONDER)


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
    return await staff_admin.reactivate(db, auth, request, admin, user_id, RESPONDER)
