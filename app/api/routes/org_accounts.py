"""An Admin's Coordinator accounts (PRD v13/v14 §4.6.4; pass 6 A48, A49, A49b).

Tier 1 creates Tier 2: every organisation's Admin creates the Coordinator
(sub_admin) accounts of its own organisation. Coordinators then create their
Responders on the mobile app (routes/team.py).

Since v1.12.51 an Admin manages them exactly as it manages Responders (23 Nov
2026: "make the account management in coordinator and responder the same"):
list them with who is on a fire, edit, move (the central hub), send a password
link, turn off and on. The rules are app/services/staff_admin.py's.

A new Coordinator signs in with an address made from their name, agency and
role (obryan.fircor@replit.com, the 6 November list). @replit.com has no
mailboxes, so the Admin gives their own email too: a link there confirms it and
sets their password, and later password resets go there as well
(app/services/staff_links.py). The Admin never handles a password.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AuthClientDep, CoordinatorManager, DatabaseDep, EmailClientDep
from app.api.routes.password_reset import reset_page_url
from app.schemas.organization import (
    CoordinatorCreateRequest,
    CoordinatorCreateResult,
    CoordinatorEmailPreview,
)
from app.schemas.team import (
    AdminCoordinator,
    AdminResponderLink,
    AdminResponderLinkSent,
    AdminResponderUpdate,
)
from app.services import staff_admin
from app.services.responder_lifecycle import COORDINATOR

router = APIRouter(prefix="/admin/coordinators", tags=["admin"])


@router.get(
    "", response_model=list[AdminCoordinator], summary="The Coordinators I manage (Admin)"
)
async def list_coordinators(
    admin: CoordinatorManager, db: DatabaseDep
) -> list[AdminCoordinator]:
    """Who is on a fire first, then who can sign in, then by name."""
    return cast(list[AdminCoordinator], await staff_admin.everyone(db, admin, COORDINATOR))


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
    email = await staff_admin.preview_address(
        db, admin, COORDINATOR, first=first_name, last=last_name, organization_id=organization_id
    )
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

    The address takes the next number when the name is taken. The link to set
    a password goes to the Coordinator's personal email.
    """
    made, sent, detail = await staff_admin.create(
        db, auth, email_client, request, admin, payload, COORDINATOR
    )
    return CoordinatorCreateResult(
        coordinator=cast(AdminCoordinator, made),
        personal_email=str(payload.personal_email).strip().lower(),
        invite_email_sent=sent,
        detail=detail,
    )


@router.patch(
    "/{user_id}",
    response_model=AdminCoordinator,
    summary="Edit a Coordinator, or move one to another organization (Admin)",
)
async def update_coordinator(
    user_id: UUID,
    payload: AdminResponderUpdate,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
) -> AdminCoordinator:
    """Only what is sent changes; an empty title or mobile clears it."""
    return cast(
        AdminCoordinator,
        await staff_admin.update(db, request, admin, user_id, payload, COORDINATOR),
    )


@router.post(
    "/{user_id}/password-link",
    response_model=AdminResponderLinkSent,
    summary="Email a Coordinator a link to set a password (Admin)",
)
async def send_password_link(
    user_id: UUID,
    payload: AdminResponderLink,
    request: Request,
    admin: CoordinatorManager,
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
        COORDINATOR,
        redirect_to=reset_page_url(),
    )
    return AdminResponderLinkSent(sent_to=to)


@router.post(
    "/{user_id}/deactivate",
    response_model=AdminCoordinator,
    summary="Turn off a Coordinator account (Admin)",
)
async def deactivate_coordinator(
    user_id: UUID,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> AdminCoordinator:
    """Turn off: the history stays, sign-in stops, a live response is released."""
    return cast(
        AdminCoordinator,
        await staff_admin.deactivate(db, auth, request, admin, user_id, COORDINATOR),
    )


@router.post(
    "/{user_id}/reactivate",
    response_model=AdminCoordinator,
    summary="Turn a Coordinator account back on (Admin)",
)
async def reactivate_coordinator(
    user_id: UUID,
    request: Request,
    admin: CoordinatorManager,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> AdminCoordinator:
    """Lift the ban. Their old password works again."""
    return cast(
        AdminCoordinator,
        await staff_admin.reactivate(db, auth, request, admin, user_id, COORDINATOR),
    )
