"""Admin-only endpoints (Section 6 RBAC): user management + KYC manual review.

RBAC is enforced by the AdminUser dependency (FastAPI layer) on top of the DB
authority triggers/RLS (defense in depth).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import AdminUser, AuthClientDep, DatabaseDep, StorageClientDep
from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.core.logging import get_logger
from app.schemas.admin import (
    AdminCreateUserRequest,
    PendingVerification,
    VerificationReviewRequest,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.verification import VerificationResultResponse

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/users",
    response_model=AuthenticatedUser,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a user with a role",
)
async def create_user(
    payload: AdminCreateUserRequest,
    admin: AdminUser,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> AuthenticatedUser:
    """Create a confirmed auth user (admin-only) and assign its role/agency/org."""
    metadata = {"full_name": payload.full_name} if payload.full_name else None
    created = await auth.admin_create_user(
        email=str(payload.email),
        password=payload.password,
        email_confirm=True,
        user_metadata=metadata,
    )
    new_id = created.get("id") or (created.get("user") or {}).get("id")
    if not isinstance(new_id, str):
        raise ExternalServiceError("User created but no id was returned by Supabase Auth.")

    row = await db.fetchrow(
        """
        update public.users
           set role = $2::public.user_role,
               agency_type = $3::public.agency_type,
               full_name = coalesce($4, full_name),
               primary_org_id = $5
         where id = $1
         returning id, email, phone, role, agency_type, verified_percent, badge,
                   full_name, primary_org_id
        """,
        UUID(new_id),
        payload.role,
        payload.agency_type,
        payload.full_name,
        payload.primary_org_id,
    )
    if row is None:
        raise ExternalServiceError("User created but the profile row was not found.")

    log.info(
        "admin_created_user",
        admin_id=str(admin.id),
        new_user_id=new_id,
        role=payload.role,
        agency_type=payload.agency_type,
    )
    return AuthenticatedUser.model_validate(dict(row))


@router.get(
    "/verifications/pending",
    response_model=list[PendingVerification],
    summary="Admin: list verifications awaiting manual review",
)
async def list_pending_verifications(
    admin: AdminUser, db: DatabaseDep, storage: StorageClientDep
) -> list[PendingVerification]:
    """List manual-review verifications, with signed URLs for any uploaded images."""
    rows = await db.fetch(
        """
        select uv.id, uv.user_id, u.email, u.full_name,
               uv.type::text as type, uv.status::text as status,
               uv.provider, uv.submitted_at,
               uv.metadata->>'id_path' as id_path,
               uv.metadata->>'selfie_path' as selfie_path
        from public.user_verifications uv
        join public.users u on u.id = uv.user_id
        where uv.status = 'manual_review'
        order by uv.submitted_at asc
        """
    )
    items: list[PendingVerification] = []
    for r in rows:
        id_url = (
            await storage.create_signed_url(bucket="national-ids", path=r["id_path"])
            if r["id_path"]
            else None
        )
        selfie_url = (
            await storage.create_signed_url(bucket="national-ids", path=r["selfie_path"])
            if r["selfie_path"]
            else None
        )
        items.append(
            PendingVerification(
                id=r["id"],
                user_id=r["user_id"],
                email=r["email"],
                full_name=r["full_name"],
                type=r["type"],
                status=r["status"],
                provider=r["provider"],
                submitted_at=r["submitted_at"],
                id_image_url=id_url,
                selfie_image_url=selfie_url,
            )
        )
    return items


@router.post(
    "/verifications/{verification_id}/approve",
    response_model=VerificationResultResponse,
    summary="Admin: approve a verification (+50%)",
)
async def approve_verification(
    verification_id: UUID, admin: AdminUser, db: DatabaseDep
) -> VerificationResultResponse:
    """Approve a manual-review verification, awarding the National ID +50%."""
    settings = get_settings()
    row = await db.fetchrow(
        """
        update public.user_verifications
           set status = 'verified', percent_awarded = $2, verified_at = now(),
               reviewed_by = $3, reviewed_at = now()
         where id = $1 and status = 'manual_review'
         returning user_id
        """,
        verification_id,
        settings.id_verification_percent,
        admin.id,
    )
    if row is None:
        raise NotFoundError("No pending verification found for that id.")
    user_row = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", row["user_id"]
    )
    assert user_row is not None
    log.info("verification_approved", admin_id=str(admin.id), verification_id=str(verification_id))
    return VerificationResultResponse(
        verified=True,
        verified_percent=user_row["verified_percent"],
        badge=str(user_row["badge"]),
        message="Verification approved (+50%).",
    )


@router.post(
    "/verifications/{verification_id}/reject",
    response_model=VerificationResultResponse,
    summary="Admin: reject a verification",
)
async def reject_verification(
    verification_id: UUID,
    payload: VerificationReviewRequest,
    admin: AdminUser,
    db: DatabaseDep,
) -> VerificationResultResponse:
    """Reject a manual-review verification (awards nothing)."""
    row = await db.fetchrow(
        """
        update public.user_verifications
           set status = 'rejected', percent_awarded = 0,
               reviewed_by = $2, reviewed_at = now(), review_notes = $3
         where id = $1 and status = 'manual_review'
         returning user_id
        """,
        verification_id,
        admin.id,
        payload.notes,
    )
    if row is None:
        raise NotFoundError("No pending verification found for that id.")
    user_row = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", row["user_id"]
    )
    assert user_row is not None
    log.info("verification_rejected", admin_id=str(admin.id), verification_id=str(verification_id))
    return VerificationResultResponse(
        verified=False,
        verified_percent=user_row["verified_percent"],
        badge=str(user_row["badge"]),
        message="Verification rejected.",
    )