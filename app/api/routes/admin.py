"""Admin-only endpoints (Section 6 RBAC): user management, KYC manual review, and
incident routing (v10 Section 2.6.2).

RBAC is enforced by the AdminUser dependency (FastAPI layer) on top of the DB
authority triggers/RLS (defense in depth).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.deps import AdminUser, AuthClientDep, DatabaseDep, StorageClientDep
from app.api.routes.incidents import finish_incident_change
from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.schemas.admin import (
    AdminCreateUserRequest,
    PendingVerification,
    RouteIncidentRequest,
    VerificationReviewRequest,
)
from app.schemas.auth import AuthenticatedUser
from app.schemas.incident import IncidentDetail
from app.schemas.verification import VerificationResultResponse
from app.services.audit import record_audit
from app.services.incident import OFF_FEED_STATUSES, routable_agencies
from app.services.incident_notify import notify_route_recipients

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


@router.post(
    "/incidents/{incident_id}/route",
    response_model=IncidentDetail,
    summary="Admin: accept an incoming incident and route it to response agencies",
)
async def route_incident(
    incident_id: UUID,
    payload: RouteIncidentRequest,
    request: Request,
    admin: AdminUser,
    db: DatabaseDep,
) -> IncidentDetail:
    """Route an incident to agencies the reporter asked for, and to chosen teams in each.

    Routing follows the report: an agency can only be routed an incident a
    reporter requested it for, which keeps visibility scoped by
    ``reports.selected_agencies`` exactly as Section 2.6.1 states. Routing does
    not verify — the Fire Volunteer coordinator still owns that transition — and
    changes no status. Routing an agency or team twice is a no-op, so the call
    can be repeated to add teams. Each call that routes something new is one
    audit_logs entry listing what was routed.
    """
    current = await db.fetchval(
        "select status::text from public.areas where id = $1", incident_id
    )
    if current is None:
        raise NotFoundError("Incident not found.")
    if current in OFF_FEED_STATUSES:
        raise ConflictError(
            "This incident is no longer live, so it cannot be routed.",
            details={"current_status": current},
        )

    requested = await db.fetchval(
        """
        select coalesce(array_agg(distinct ag), '{}')
        from public.area_reports ar
        join public.reports r on r.id = ar.report_id
        cross join lateral unnest(r.selected_agencies::text[]) as ag
        where ar.area_id = $1
        """,
        incident_id,
    )
    routable = routable_agencies(requested or [])
    unrequested = [t.agency for t in payload.routes if t.agency not in routable]
    if unrequested:
        raise BadRequestError(
            "Routing follows the agencies the reporter asked for, and this report did "
            f"not ask for: {', '.join(unrequested)}.",
            details={"routable_agencies": sorted(routable)},
        )

    wanted_orgs = [org for t in payload.routes for org in t.organization_ids]
    orgs: dict[UUID, dict[str, object]] = {}
    if wanted_orgs:
        rows = await db.fetch(
            """
            select id, name, agency_type::text as agency_type, is_active
            from public.organizations where id = any($1::uuid[])
            """,
            wanted_orgs,
        )
        orgs = {r["id"]: dict(r) for r in rows}
    for target in payload.routes:
        for org_id in target.organization_ids:
            org = orgs.get(org_id)
            if org is None:
                raise BadRequestError(f"Organization {org_id} does not exist.")
            if org["agency_type"] != target.agency:
                raise BadRequestError(
                    f"{org['name']} is not a {target.agency} team; route it under its own agency."
                )
            if not org["is_active"]:
                raise BadRequestError(f"{org['name']} is inactive and cannot be alerted.")

    newly: list[tuple[str, UUID | None]] = []
    async with db.acquire() as conn, conn.transaction():
        for target in payload.routes:
            # No teams chosen means the agency as a whole: one row, organization null.
            teams: list[UUID | None] = [*target.organization_ids] or [None]
            for team_id in teams:
                inserted = await conn.fetchval(
                    """
                    insert into public.area_routes (area_id, agency, organization_id, routed_by)
                    values ($1, $2::public.agency_type, $3, $4)
                    on conflict on constraint area_routes_unique do nothing
                    returning id
                    """,
                    incident_id,
                    target.agency,
                    team_id,
                    admin.id,
                )
                if inserted is not None:
                    newly.append((target.agency, team_id))
        if newly:
            await record_audit(
                conn,
                request,
                admin,
                action="incident.route",
                entity_type="area",
                entity_id=incident_id,
                area_id=incident_id,
                metadata={
                    "routes": [
                        {
                            "agency": agency,
                            "organization_id": str(org_id) if org_id else None,
                            "organization_name": orgs[org_id]["name"] if org_id else None,
                        }
                        for agency, org_id in newly
                    ],
                    "status_at_route": current,
                    "notes": payload.notes,
                },
            )

    if newly:
        log.info(
            "incident_routed",
            incident_id=str(incident_id),
            admin_id=str(admin.id),
            routes=len(newly),
        )
        try:
            await notify_route_recipients(db, incident_id, newly)
        except Exception:
            log.error("route_notify_failed", incident_id=str(incident_id), exc_info=True)
    return await finish_incident_change(db, incident_id, "incident_routed")