"""Admin-only endpoints (Section 6 RBAC): user management, KYC manual review, and
incident routing (v10 Section 2.6.2).

RBAC is enforced by permission-scoped Admin dependencies (app/api/deps.py,
app/services/access.py) on top of the DB authority triggers/RLS (defense in
depth): creating an account of any role is the system Admin's, National ID
review the central hub's.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import (
    AnyAccountAdmin,
    AuthClientDep,
    DatabaseDep,
    IdReviewer,
    StorageClientDep,
)
from app.core.config import get_settings
from app.core.exceptions import (
    ExternalServiceError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.supabase_storage import SupabaseStorageClient
from app.schemas.admin import (
    AdminCreateUserRequest,
    PendingVerification,
    VerificationApproveRequest,
    VerificationReviewRequest,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.verification import VerificationResultResponse
from app.services.national_id import BUCKET, notify_review_decided, remove_photos

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_QR_FILENAME = "philsys-qr.jpg"


@router.post(
    "/users",
    response_model=AuthenticatedUser,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a user with a role",
)
async def create_user(
    payload: AdminCreateUserRequest,
    admin: AnyAccountAdmin,
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


async def _signed_url(storage: SupabaseStorageClient, path: str | None) -> str | None:
    return await storage.create_signed_url(bucket=BUCKET, path=path) if path else None


@router.get(
    "/verifications/pending",
    response_model=list[PendingVerification],
    summary="Admin: list verifications awaiting manual review",
)
async def list_pending_verifications(
    admin: IdReviewer, db: DatabaseDep, storage: StorageClientDep
) -> list[PendingVerification]:
    """List manual-review verifications, with signed URLs for any uploaded images."""
    rows = await db.fetch(
        """
        select uv.id, uv.user_id, u.email, u.full_name,
               uv.type::text as type, uv.status::text as status,
               uv.provider, uv.submitted_at,
               uv.metadata->>'id_path' as id_path,
               uv.metadata->>'selfie_path' as selfie_path,
               uv.metadata->>'qr_path' as qr_path
        from public.user_verifications uv
        join public.users u on u.id = uv.user_id
        where uv.status = 'manual_review'
        order by uv.submitted_at asc
        """
    )
    items: list[PendingVerification] = []
    for r in rows:
        qr_url = await _signed_url(storage, r["qr_path"])
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
                id_image_url=await _signed_url(storage, r["id_path"]),
                selfie_image_url=await _signed_url(storage, r["selfie_path"]),
                qr_image_url=qr_url,
                qr_download_url=f"{qr_url}&download={_QR_FILENAME}" if qr_url else None,
            )
        )
    return items


async def _discard_photos(
    db: Database, storage: SupabaseStorageClient, verification_id: UUID
) -> None:
    """Delete a pending review's photos, before its decision is recorded.

    In that order a decided review never holds them: if recording fails, the
    reviewer decides again and the photos are simply already gone.
    """
    row = await db.fetchrow(
        """
        select metadata->>'id_path' as id_path,
               metadata->>'selfie_path' as selfie_path,
               metadata->>'qr_path' as qr_path
        from public.user_verifications
        where id = $1 and status = 'manual_review'
        """,
        verification_id,
    )
    if row is None:
        raise NotFoundError("No pending verification found for that id.")
    await remove_photos(storage, (row["id_path"], row["selfie_path"], row["qr_path"]))


async def _tell_resident(
    db: Database, user_id: UUID, *, approved: bool, notes: str | None = None
) -> None:
    """The resident hears the decision on their phone; never fail the decision."""
    try:
        await notify_review_decided(db, user_id, approved=approved, notes=notes)
    except Exception:
        log.error("national_id_notify_failed", user_id=str(user_id), exc_info=True)


@router.post(
    "/verifications/{verification_id}/approve",
    response_model=VerificationResultResponse,
    summary="Admin: approve a verification (+50%)",
)
async def approve_verification(
    verification_id: UUID,
    payload: VerificationApproveRequest,
    admin: IdReviewer,
    db: DatabaseDep,
    storage: StorageClientDep,
) -> VerificationResultResponse:
    """Approve a manual-review verification, awarding the National ID +50%."""
    settings = get_settings()
    await _discard_photos(db, storage, verification_id)
    row = await db.fetchrow(
        """
        update public.user_verifications
           set status = 'verified', percent_awarded = $2, verified_at = now(),
               reviewed_by = $3, reviewed_at = now(),
               metadata = (metadata - 'id_path' - 'selfie_path' - 'qr_path')
                          || jsonb_build_object('philsys_result', $4::text)
         where id = $1 and status = 'manual_review'
         returning user_id
        """,
        verification_id,
        settings.id_verification_percent,
        admin.id,
        payload.philsys_result,
    )
    if row is None:
        raise NotFoundError("No pending verification found for that id.")
    user_row = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", row["user_id"]
    )
    assert user_row is not None
    log.info("verification_approved", admin_id=str(admin.id), verification_id=str(verification_id))
    await _tell_resident(db, row["user_id"], approved=True)
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
    admin: IdReviewer,
    db: DatabaseDep,
    storage: StorageClientDep,
) -> VerificationResultResponse:
    """Reject a manual-review verification (awards nothing)."""
    await _discard_photos(db, storage, verification_id)
    row = await db.fetchrow(
        """
        update public.user_verifications
           set status = 'rejected', percent_awarded = 0,
               reviewed_by = $2, reviewed_at = now(), review_notes = $3,
               metadata = (metadata - 'id_path' - 'selfie_path' - 'qr_path')
                          || jsonb_strip_nulls(jsonb_build_object('philsys_result', $4::text))
         where id = $1 and status = 'manual_review'
         returning user_id
        """,
        verification_id,
        admin.id,
        payload.notes,
        payload.philsys_result,
    )
    if row is None:
        raise NotFoundError("No pending verification found for that id.")
    user_row = await db.fetchrow(
        "select verified_percent, badge from public.users where id = $1", row["user_id"]
    )
    assert user_row is not None
    log.info("verification_rejected", admin_id=str(admin.id), verification_id=str(verification_id))
    await _tell_resident(db, row["user_id"], approved=False, notes=payload.notes)
    return VerificationResultResponse(
        verified=False,
        verified_percent=user_row["verified_percent"],
        badge=str(user_row["badge"]),
        message="Verification rejected.",
    )


# v11 removed Admin's manual routing (Section 2.6.2). The reporter's
# `selected_agencies` already carries the intent, so every agency a reporter
# asked for sees the Area on its own surface with its own Accept button, and
# Admin re-selecting the same list was busywork. Admin keeps an Accept of its
# own — `POST /incidents/{id}/accept` — as the safety net for an Area nobody
# else has picked up.