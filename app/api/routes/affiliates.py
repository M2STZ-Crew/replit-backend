"""Affiliate onboarding endpoints (Phase 12, Section 7 #2).

An organization applies on the public form (or a signed-in user submits for
one); the central hub reviews. Accepting creates the organization and its
first Coordinator together, or neither.

Since v1.12.51 that Coordinator is always a new account, made like every
other Coordinator since 6 November 2026: a made @replit.com sign-in, and a link
to the contact email that confirms it and sets the password. An account that
already exists is never touched, whatever its email.
"""

from __future__ import annotations

import json
import secrets
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request, status

from app.api.deps import (
    AffiliateReviewer,
    AuthClientDep,
    CurrentUser,
    DatabaseDep,
    EmailClientDep,
)
from app.core.exceptions import AppError, BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.integrations.brevo_email import BrevoEmailClient
from app.schemas.affiliate import (
    AffiliateAcceptRequest,
    AffiliateAcceptResult,
    AffiliatePublicRegister,
    AffiliateRequestCreate,
    AffiliateRequestResponse,
    AffiliateReviewRequest,
)
from app.services import responder_lifecycle as lifecycle
from app.services import staff_admin
from app.services.audit import record_audit
from app.services.disposable_email import ensure_not_disposable
from app.services.email_deliverability import ensure_deliverable
from app.services.email_layout import RenderedEmail, render_email
from app.services.names import ensure_valid_name, one_line
from app.services.responder_accounts import is_staff_address
from app.services.responder_lifecycle import COORDINATOR

log = get_logger(__name__)

router = APIRouter(prefix="/affiliates", tags=["affiliates"])

_COLS = (
    "id, organization_name, agency_type::text as agency_type, requested_by, "
    "contact_name, contact_email, contact_phone, address, message, "
    "status::text as status, organization_id, reviewed_by, reviewed_at, "
    "review_notes, details, created_at, updated_at"
)


def _decoded(raw: Any) -> dict[str, Any] | None:
    """A jsonb ``details`` as asyncpg gives it (a str: no codec is registered)."""
    if isinstance(raw, str):
        raw = json.loads(raw) if raw else None
    return raw if isinstance(raw, dict) else None


def _to_response(row: Any) -> AffiliateRequestResponse:
    """Build the response model from a row, parsing the ``details`` jsonb str."""
    data = dict(row)
    data["details"] = _decoded(data.get("details"))
    return AffiliateRequestResponse.model_validate(data)


async def _ensure_contact(email: str) -> None:
    """A contact email the Coordinator's link can reach: a 400 otherwise."""
    ensure_not_disposable(email, field="contact_email")
    if is_staff_address(email):
        raise BadRequestError(
            "Use your own email: @replit.com addresses have no mailbox.",
            error_code="not_personal",
            details={"field": "contact_email"},
        )
    await ensure_deliverable(email)


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #
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
    if payload.contact_email:
        await _ensure_contact(str(payload.contact_email))
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


def _received_email() -> RenderedEmail:
    """'We have your application' (HTML and plain text). Carries nothing the
    applicant typed: the form is public, so anything echoed here could be used
    to send spam."""
    return render_email(
        preheader="An administrator will review your application to join RepLiT.",
        heading="We received your application",
        paragraphs=[
            "Thank you for applying to join RepLiT as an affiliate organization. An "
            "administrator will review your application.",
            "Once it is approved, we will email this address your Coordinator's "
            "sign-in and a link to set its password.",
        ],
        notice="If you did not apply, you can ignore this email.",
        reason="You are receiving this email because this address was given as the "
        "contact on an application to join RepLiT.",
    )


# One acknowledgement per address in this window, however often the public
# form is submitted with it.
_RECEIVED_EMAIL_WINDOW_MIN = 10
# And no more than this an hour in all: the form is public, and password resets
# share the mail server's daily allowance. Applications are stored regardless.
_RECEIVED_EMAILS_AN_HOUR = 30


async def _send_received_email(email_client: BrevoEmailClient, to: str) -> None:
    """Best effort: a failed acknowledgement must not lose the application."""
    try:
        message = _received_email()
        await email_client.send(
            to=to,
            subject="We received your RepLiT affiliate application",
            html=message.html,
            text=message.text,
        )
    except AppError as exc:
        log.warning("affiliate_received_email_failed", error=str(exc))


@router.post(
    "/register",
    response_model=AffiliateRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Public affiliate registration (no account required)",
)
async def register_affiliate(
    payload: AffiliatePublicRegister,
    db: DatabaseDep,
    email_client: EmailClientDep,
    background: BackgroundTasks,
) -> AffiliateRequestResponse:
    """Public affiliation form: an org applies before having an account.

    requested_by is null; the contact person, roster, equipment and SEC-cert
    metadata are captured in ``details`` (jsonb) and summarized into
    ``message`` for the admin queue. The applicant is emailed straight away
    that it arrived, and again with the Coordinator's sign-in when the hub
    accepts, so a contact email that takes no mail is refused.
    """
    email = str(payload.contact_email)
    await _ensure_contact(email)
    first, last = payload.contact_first_name, payload.contact_last_name
    contact_name = ensure_valid_name(" ".join(p for p in (first, last) if p))
    skip_email = await db.fetchval(
        "select exists (select 1 from public.affiliate_requests "
        "where lower(contact_email) = lower($1) "
        "and created_at > now() - make_interval(mins => $2))",
        email,
        _RECEIVED_EMAIL_WINDOW_MIN,
    )
    if not skip_email:
        this_hour = await db.fetchval(
            "select count(*) from public.affiliate_requests "
            "where requested_by is null and created_at > now() - interval '1 hour'"
        )
        skip_email = int(this_hour or 0) >= _RECEIVED_EMAILS_AN_HOUR
    details = {
        "roster": [m.model_dump() for m in payload.roster],
        "equipment": [e.model_dump() for e in payload.equipment],
        "sec_certificate_name": payload.sec_certificate_name,
        "contact_first_name": first,
        "contact_last_name": last,
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
             contact_phone, address, message, details, contact_name)
        values ($1, $2::public.agency_type, null, $3, $4, $5, $6, $7::jsonb, $8)
        returning {_COLS}
        """,
        payload.organization_name,
        payload.agency_type,
        email,
        payload.contact_phone,
        payload.address,
        message,
        json.dumps(details),
        contact_name,
    )
    assert row is not None
    log.info(
        "affiliate_public_registered",
        request_id=str(row["id"]),
        org=payload.organization_name,
    )
    # After the response, so a slow mail server never holds up the form.
    if not skip_email:
        background.add_task(_send_received_email, email_client, email)
    return _to_response(row)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
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
    admin: AffiliateReviewer,
    db: DatabaseDep,
    status_filter: Annotated[
        Literal["pending", "approved", "rejected"] | None, Query(alias="status")
    ] = None,
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


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #
def _coordinator_name(payload: AffiliateAcceptRequest, req: Any) -> tuple[str, str]:
    """The first Coordinator's name: what the hub typed, else the form's."""
    details = _decoded(req["details"]) or {}
    first = one_line(payload.coordinator_first_name or details.get("contact_first_name"))
    last = one_line(payload.coordinator_last_name or details.get("contact_last_name"))
    if not first or not last:
        raise BadRequestError(
            "Enter the Coordinator's first name and surname. Their sign-in is made from it.",
            error_code="coordinator_name_needed",
            details={"field": "coordinator_first_name"},
        )
    return first, last


@router.post(
    "/{request_id}/accept",
    response_model=AffiliateAcceptResult,
    summary="Approve an affiliate request (admin): the org and a new Coordinator account",
)
async def accept_affiliate_request(
    request_id: UUID,
    payload: AffiliateAcceptRequest,
    request: Request,
    admin: AffiliateReviewer,
    db: DatabaseDep,
    auth: AuthClientDep,
    email_client: EmailClientDep,
) -> AffiliateAcceptResult:
    """Approve a pending request once: the organization, its Coordinator's
    account and the audit lines in one transaction, then the email.

    With no contact email there is no Coordinator yet: the hub creates one
    under Accounts.
    """
    req = await db.fetchrow(
        """
        select organization_name, agency_type::text as agency_type, contact_email,
               contact_phone, address, details, status::text as status
          from public.affiliate_requests
         where id = $1
        """,
        request_id,
    )
    if req is None:
        raise NotFoundError("Affiliate request not found.")
    if req["status"] != "pending":
        raise ConflictError("This affiliate request has already been reviewed.")

    org_name = one_line(req["organization_name"])
    if not org_name:
        raise BadRequestError("This application names no organization. Decline it.")
    agency = req["agency_type"]
    personal = str(req["contact_email"] or "").strip().lower()
    full_name = address = ""
    new_id: UUID | None = None
    if personal:
        if is_staff_address(personal):
            raise BadRequestError(
                "This application gives an @replit.com address, which has no mailbox. "
                "Decline it and ask them to apply with their own email.",
                error_code="not_personal",
            )
        first, last = _coordinator_name(payload, req)
        full_name = staff_admin.valid_name(f"{first} {last}")
        new_id, address = await lifecycle.make_sign_in(
            db,
            auth,
            first=first,
            last=last,
            agency=agency,
            # Never used: they set their own from the email.
            password=secrets.token_urlsafe(24),
            kind=COORDINATOR,
        )

    try:
        async with db.acquire() as conn, conn.transaction():
            # Locked: of two Accepts at once, the second finds it reviewed.
            state = await conn.fetchval(
                "select status::text from public.affiliate_requests where id = $1 for update",
                request_id,
            )
            if state != "pending":
                raise ConflictError("This affiliate request has already been reviewed.")
            org_id = await conn.fetchval(
                """
                insert into public.organizations
                    (name, agency_type, contact_email, contact_phone, address)
                values ($1, $2::public.agency_type, $3, $4, $5)
                returning id
                """,
                org_name,
                agency,
                req["contact_email"],
                req["contact_phone"],
                req["address"],
            )
            row = await conn.fetchrow(
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
            await record_audit(
                conn,
                request,
                admin,
                action="affiliate.accept",
                entity_type="organization",
                entity_id=org_id,
                after_state={"agency": agency, "coordinator": address or None},
                metadata={"organization": org_name, "request_id": str(request_id)},
            )
            if new_id is not None:
                await lifecycle.write_profile(
                    conn,
                    COORDINATOR,
                    new_id,
                    agency=agency,
                    org_id=org_id,
                    full_name=full_name,
                    mobile=None,
                    created_by=admin.id,
                    personal=personal,
                )
                await lifecycle.put_on_roster(conn, COORDINATOR, org_id, new_id, None)
                await record_audit(
                    conn,
                    request,
                    admin,
                    action="user.coordinator_created",
                    entity_type="user",
                    entity_id=new_id,
                    after_state={
                        "email": address,
                        "personal_email": personal,
                        "role": COORDINATOR.role,
                        "agency": agency,
                        "organization_id": str(org_id),
                    },
                    metadata={"coordinator": full_name, "via": "affiliation"},
                )
    except Exception:
        if new_id is not None:
            await lifecycle.discard_sign_in(auth, new_id)
        raise

    sent = False
    detail: str | None = (
        "No contact email on the request, so no account was created. "
        "Create the Coordinator under Accounts."
    )
    if new_id is not None:
        sent, detail = await lifecycle.send_welcome(
            email_client,
            user_id=new_id,
            name=full_name,
            organization=org_name,
            address=address,
            personal=personal,
            made_by=(
                "The RepLiT central hub" if admin.org_is_central_hub else "A RepLiT Admin"
            ),
            kind=COORDINATOR,
        )

    log.info(
        "affiliate_request_approved",
        request_id=str(request_id),
        org_id=str(org_id),
        by=str(admin.id),
        account_provisioned=new_id is not None,
        invite_email_sent=sent,
    )
    return AffiliateAcceptResult(
        request=_to_response(row),
        account_email=personal or None,
        sign_in_address=address or None,
        account_provisioned=new_id is not None,
        account_created=new_id is not None,
        invite_email_sent=sent,
        detail=detail,
    )


@router.post(
    "/{request_id}/reject",
    response_model=AffiliateRequestResponse,
    summary="Reject an affiliate request (admin)",
)
async def reject_affiliate_request(
    request_id: UUID,
    payload: AffiliateReviewRequest,
    request: Request,
    admin: AffiliateReviewer,
    db: DatabaseDep,
) -> AffiliateRequestResponse:
    """Reject a pending affiliation request (admin)."""
    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
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
        await record_audit(
            conn,
            request,
            admin,
            action="affiliate.decline",
            entity_type="affiliate_request",
            entity_id=request_id,
            metadata={"organization": row["organization_name"], "notes": payload.notes},
        )
    log.info("affiliate_request_rejected", request_id=str(request_id), by=str(admin.id))
    return _to_response(row)
