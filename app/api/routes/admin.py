"""Admin-only user management endpoints (Section 6 RBAC).

The admin-creates-user flow creates a confirmed auth user via the GoTrue admin API
(service_role), then elevates the auto-provisioned public.users row to the assigned
role + agency. RBAC is enforced by the AdminUser dependency (FastAPI layer) on top
of the DB authority triggers/RLS (defense in depth).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import AdminUser, AuthClientDep, DatabaseDep
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.schemas.admin import AdminCreateUserRequest
from app.schemas.auth import AuthenticatedUser

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
         returning id, email, phone, role, agency_type, verified_percent,
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