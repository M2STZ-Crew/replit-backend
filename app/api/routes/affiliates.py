"""Affiliate onboarding endpoints (Phase 12, Section 7 #2).

Any authenticated user submits an affiliation request for an organization; admins
review. Approval creates the organization and links it back to the request.
"""

from __future__ import annotations

import json
import secrets
from typing import Annotated, Any, TypedDict
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AdminUser,
    AuthClientDep,
    CurrentUser,
    DatabaseDep,
    EmailClientDep,
)
from app.core.exceptions import AppError, BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.supabase_auth import AuthError, SupabaseAuthClient
from app.schemas.affiliate import (
    AffiliateAcceptResult,
    AffiliatePublicRegister,
    AffiliateRequestCreate,
    AffiliateRequestResponse,
    AffiliateReviewRequest,
)

log = get_logger(__name__)

router = APIRouter(prefix="/affiliates", tags=["affiliates"])

_COLS = (
    "id, organization_name, agency_type::text as agency_type, requested_by, "
    "contact_name, contact_email, contact_phone, address, message, "
    "status::text as status, organization_id, reviewed_by, reviewed_at, "
    "review_notes, details, created_at, updated_at"
)


def _to_response(row: Any) -> AffiliateRequestResponse:
    """Build the response model from a row, parsing the ``details`` jsonb str.

    asyncpg returns jsonb as a ``str`` (no JSON codec is registered), so decode
    it back into a dict before pydantic validation.
    """
    data = dict(row)
    raw = data.get("details")
    if isinstance(raw, str):
        data["details"] = json.loads(raw) if raw else None
    return AffiliateRequestResponse.model_validate(data)


class _AccountStatus(TypedDict):
    """Sub-admin provisioning outcome for an accepted affiliate."""

    account_email: str | None
    account_provisioned: bool
    account_created: bool
    invite_email_sent: bool
    detail: str | None


def _approval_email_html(org_name: str, link: str) -> str:
    """Branded 'you're approved — set your password' email (HTML)."""
    return (
        '<div style="font-family:Inter,Arial,sans-serif;color:#111;max-width:520px">'
        f"<h2 style='margin:0 0 12px'>Welcome to RepLiT, {org_name}!</h2>"
        "<p>Your affiliate organization has been <b>approved</b>. A sub-admin "
        "account has been created for this email address.</p>"
        "<p>Set your password to start using the RepLiT sub-admin dashboard on the "
        "mobile app:</p>"
        f'<p><a href="{link}" style="display:inline-block;background:#EB4800;'
        'color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;'
        'font-weight:bold">Set my password</a></p>'
        '<p style="color:#666;font-size:13px">If the button does not work, copy this '
        f"link into your browser:<br>{link}</p>"
        "</div>"
    )


def _approval_email_text(org_name: str, link: str) -> str:
    """Plain-text fallback for the approval email."""
    return (
        f"Welcome to RepLiT, {org_name}!\n\n"
        "Your affiliate organization has been approved and a sub-admin account was "
        "created for this email address.\n\n"
        f"Set your password to sign in to the mobile sub-admin dashboard:\n{link}\n"
    )


async def _provision_subadmin(
    auth: SupabaseAuthClient,
    email_client: BrevoEmailClient,
    db: Database,
    *,
    email: str,
    full_name: str | None,
    agency_type: str,
    org_id: UUID,
    org_name: str,
) -> _AccountStatus:
    """Create (or promote) a sub_admin user for an accepted affiliate and email a
    password-setup link. Best-effort: returns status flags and never raises so an
    email/auth hiccup cannot roll back the approval itself.
    """
    info: _AccountStatus = {
        "account_email": email,
        "account_provisioned": False,
        "account_created": False,
        "invite_email_sent": False,
        "detail": None,
    }

    # Create the auth user (confirmed); they set their own password via the email.
    user_id: UUID | None = None
    try:
        created = await auth.admin_create_user(
            email=email,
            password=secrets.token_urlsafe(18),
            email_confirm=True,
            user_metadata={"full_name": full_name} if full_name else None,
        )
        new_id = created.get("id") or (created.get("user") or {}).get("id")
        if isinstance(new_id, str):
            user_id = UUID(new_id)
            info["account_created"] = True
    except (BadRequestError, AuthError):
        user_id = None  # email already has an account → promote the existing profile
    except AppError as exc:
        info["detail"] = f"Auth service error while creating the account: {exc}"
        return info

    if user_id is None:
        existing = await db.fetchval(
            "select id from public.users where lower(email) = lower($1)", email
        )
        user_id = existing if existing is not None else None
    if user_id is None:
        info["detail"] = "Could not create or locate an account for this email."
        return info

    # Promote to sub_admin of the new org (never demote an existing admin).
    result = await db.execute(
        """
        update public.users
           set role = 'sub_admin'::public.user_role,
               agency_type = $2::public.agency_type,
               primary_org_id = $3,
               full_name = coalesce(full_name, $4)
         where id = $1 and role <> 'admin'::public.user_role
        """,
        user_id,
        agency_type,
        org_id,
        full_name or org_name,
    )
    if result.endswith(" 0"):
        info["detail"] = "Existing account is an administrator; left unchanged."
        return info
    info["account_provisioned"] = True

    # Email a branded password-setup link (GoTrue-generated recovery link).
    try:
        link_resp = await auth.admin_generate_link(link_type="recovery", email=email)
        action_link = link_resp.get("action_link") or (
            link_resp.get("properties") or {}
        ).get("action_link")
        if isinstance(action_link, str) and action_link:
            await email_client.send(
                to=email,
                subject="Your RepLiT affiliate account is approved",
                html=_approval_email_html(org_name, action_link),
                text=_approval_email_text(org_name, action_link),
            )
            info["invite_email_sent"] = True
        else:
            info["detail"] = "Account ready, but no password link was generated."
    except AppError as exc:
        info["detail"] = f"Account ready; setup email could not be sent ({exc})."
        log.warning("affiliate_setup_email_failed", org_id=str(org_id), error=str(exc))

    return info


@router.post(
    "",
    response_model=AffiliateRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an affiliate (organization onboarding) request",
)
async def submit_affiliate_request(
    payload: AffiliateRequestCreate, user: CurrentUser, db: DatabaseDep
) -> AffiliateRequestResponse:
    """Submit a pending affiliation request for an organization."""
    row = await db.fetchrow(
        f"""
        insert into public.affiliate_requests
            (organization_name, agency_type, requested_by, contact_name,
             contact_email, contact_phone, message)
        values ($1, $2::public.agency_type, $3, $4, $5, $6, $7)
        returning {_COLS}
        """,
        payload.organization_name,
        payload.agency_type,
        user.id,
        payload.contact_name,
        str(payload.contact_email) if payload.contact_email else None,
        payload.contact_phone,
        payload.message,
    )
    assert row is not None
    log.info("affiliate_request_submitted", request_id=str(row["id"]), by=str(user.id))
    return _to_response(row)


@router.post(
    "/register",
    response_model=AffiliateRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Public affiliate registration (no account required)",
)
async def register_affiliate(
    payload: AffiliatePublicRegister, db: DatabaseDep
) -> AffiliateRequestResponse:
    """Public affiliation form: an org applies before having an account.

    requested_by is null; the roster/equipment/SEC-cert metadata is captured in
    ``details`` (jsonb) and summarized into ``message`` for the admin queue. On
    approval an admin creates the org and credentials are issued out-of-band.
    """
    details = {
        "roster": [m.model_dump() for m in payload.roster],
        "equipment": [e.model_dump() for e in payload.equipment],
        "sec_certificate_name": payload.sec_certificate_name,
    }
    summary = [
        f"Address: {payload.address}" if payload.address else None,
        f"Roster: {len(payload.roster)} member(s)",
        f"Equipment: {len(payload.equipment)} unit(s)",
        f"SEC certificate: {payload.sec_certificate_name}"
        if payload.sec_certificate_name
        else None,
    ]
    message = "\n".join(line for line in summary if line)
    row = await db.fetchrow(
        f"""
        insert into public.affiliate_requests
            (organization_name, agency_type, requested_by, contact_email,
             contact_phone, address, message, details)
        values ($1, $2::public.agency_type, null, $3, $4, $5, $6, $7::jsonb)
        returning {_COLS}
        """,
        payload.organization_name,
        payload.agency_type,
        str(payload.contact_email),
        payload.contact_phone,
        payload.address,
        message,
        json.dumps(details),
    )
    assert row is not None
    log.info(
        "affiliate_public_registered",
        request_id=str(row["id"]),
        org=payload.organization_name,
    )
    return _to_response(row)


@router.get(
    "/mine",
    response_model=list[AffiliateRequestResponse],
    summary="List my affiliate requests",
)
async def my_affiliate_requests(
    user: CurrentUser, db: DatabaseDep
) -> list[AffiliateRequestResponse]:
    """List the caller's own affiliation requests."""
    rows = await db.fetch(
        f"select {_COLS} from public.affiliate_requests "
        "where requested_by = $1 order by created_at desc",
        user.id,
    )
    return [_to_response(r) for r in rows]


@router.get(
    "",
    response_model=list[AffiliateRequestResponse],
    summary="List affiliate requests (admin)",
)
async def list_affiliate_requests(
    admin: AdminUser,
    db: DatabaseDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[AffiliateRequestResponse]:
    """List affiliation requests, optionally filtered by status (admin)."""
    if status_filter is not None:
        rows = await db.fetch(
            f"select {_COLS} from public.affiliate_requests "
            "where status = $1::public.request_status order by created_at desc",
            status_filter,
        )
    else:
        rows = await db.fetch(
            f"select {_COLS} from public.affiliate_requests order by created_at desc"
        )
    return [_to_response(r) for r in rows]


@router.post(
    "/{request_id}/accept",
    response_model=AffiliateAcceptResult,
    summary="Approve an affiliate request (admin) — creates the org + a sub-admin account",
)
async def accept_affiliate_request(
    request_id: UUID,
    payload: AffiliateReviewRequest,
    admin: AdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> AffiliateAcceptResult:
    """Approve a pending request: create the organization, provision a sub-admin
    account on the registered email, and send a password-setup email.
    """
    req = await db.fetchrow(
        """
        select organization_name, agency_type::text as agency_type, contact_name,
               contact_email, contact_phone, status::text as status
        from public.affiliate_requests
        where id = $1
        """,
        request_id,
    )
    if req is None:
        raise NotFoundError("Affiliate request not found.")
    if req["status"] != "pending":
        raise ConflictError("This affiliate request has already been reviewed.")

    org_id = await db.fetchval(
        """
        insert into public.organizations (name, agency_type, contact_email, contact_phone)
        values ($1, $2::public.agency_type, $3, $4)
        returning id
        """,
        req["organization_name"],
        req["agency_type"],
        req["contact_email"],
        req["contact_phone"],
    )
    row = await db.fetchrow(
        f"""
        update public.affiliate_requests
           set status = 'approved', organization_id = $2, reviewed_by = $3,
               reviewed_at = now(), review_notes = $4
         where id = $1
        returning {_COLS}
        """,
        request_id,
        org_id,
        admin.id,
        payload.notes,
    )
    assert row is not None

    # Provision the org's sub-admin login on the email they registered with.
    if req["contact_email"]:
        account = await _provision_subadmin(
            auth,
            email_client,
            db,
            email=req["contact_email"],
            full_name=req["contact_name"],
            agency_type=req["agency_type"],
            org_id=org_id,
            org_name=req["organization_name"],
        )
    else:
        account = {
            "account_email": None,
            "account_provisioned": False,
            "account_created": False,
            "invite_email_sent": False,
            "detail": "No contact email on the request; no account was created.",
        }

    log.info(
        "affiliate_request_approved",
        request_id=str(request_id),
        org_id=str(org_id),
        by=str(admin.id),
        account_provisioned=account["account_provisioned"],
        invite_email_sent=account["invite_email_sent"],
    )
    return AffiliateAcceptResult(
        request=_to_response(row),
        account_email=account["account_email"],
        account_provisioned=account["account_provisioned"],
        account_created=account["account_created"],
        invite_email_sent=account["invite_email_sent"],
        detail=account["detail"],
    )


@router.post(
    "/{request_id}/reject",
    response_model=AffiliateRequestResponse,
    summary="Reject an affiliate request (admin)",
)
async def reject_affiliate_request(
    request_id: UUID, payload: AffiliateReviewRequest, admin: AdminUser, db: DatabaseDep
) -> AffiliateRequestResponse:
    """Reject a pending affiliation request (admin)."""
    row = await db.fetchrow(
        f"""
        update public.affiliate_requests
           set status = 'rejected', reviewed_by = $2, reviewed_at = now(),
               review_notes = $3
         where id = $1 and status = 'pending'
        returning {_COLS}
        """,
        request_id,
        admin.id,
        payload.notes,
    )
    if row is None:
        raise NotFoundError("No pending affiliate request found for that id.")
    log.info("affiliate_request_rejected", request_id=str(request_id), by=str(admin.id))
    return _to_response(row)