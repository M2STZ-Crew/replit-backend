"""Affiliate onboarding endpoints (Phase 12, Section 7 #2).

Any authenticated user submits an affiliation request for an organization; admins
review. Approval creates the organization and links it back to the request.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, CurrentUser, DatabaseDep
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.schemas.affiliate import (
    AffiliateRequestCreate,
    AffiliateRequestResponse,
    AffiliateReviewRequest,
)

log = get_logger(__name__)

router = APIRouter(prefix="/affiliates", tags=["affiliates"])

_COLS = (
    "id, organization_name, agency_type::text as agency_type, requested_by, "
    "contact_name, contact_email, contact_phone, message, status::text as status, "
    "organization_id, reviewed_by, reviewed_at, review_notes, created_at, updated_at"
)


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
    return AffiliateRequestResponse.model_validate(dict(row))


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
    return [AffiliateRequestResponse.model_validate(dict(r)) for r in rows]


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
    return [AffiliateRequestResponse.model_validate(dict(r)) for r in rows]


@router.post(
    "/{request_id}/accept",
    response_model=AffiliateRequestResponse,
    summary="Approve an affiliate request (admin) — creates the organization",
)
async def accept_affiliate_request(
    request_id: UUID, payload: AffiliateReviewRequest, admin: AdminUser, db: DatabaseDep
) -> AffiliateRequestResponse:
    """Approve a pending request: create the organization and link it back."""
    req = await db.fetchrow(
        """
        select organization_name, agency_type::text as agency_type,
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
    log.info(
        "affiliate_request_approved",
        request_id=str(request_id),
        org_id=str(org_id),
        by=str(admin.id),
    )
    return AffiliateRequestResponse.model_validate(dict(row))


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
    return AffiliateRequestResponse.model_validate(dict(row))