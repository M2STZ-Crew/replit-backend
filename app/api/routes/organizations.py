"""Affiliate organization directory endpoints.

Read-only views over public.organizations and their personnel (public.users by
primary_org_id) for the admin web "Affiliate Organizations" directory. Equipment
for an organization is read via the existing /equipment endpoint.

/organizations/mine/members is the one staff-facing route: a team captain's own
people, which the Post-Incident Report offers to pick the driver and roster
from instead of having names typed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import AdminUser, DatabaseDep, StaffUser
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.organization import OrganizationMember, OrganizationSummary

log = get_logger(__name__)

router = APIRouter(prefix="/organizations", tags=["organizations"])

_ORG_COLS = (
    "o.id, o.name, o.agency_type::text as agency_type, o.description, "
    "o.contact_email, o.contact_phone, o.address, o.is_active, o.created_at, "
    "(select count(*) from public.users u where u.primary_org_id = o.id) "
    "as personnel_count, "
    "(select count(*) from public.equipment e where e.organization_id = o.id) "
    "as equipment_count"
)


@router.get(
    "",
    response_model=list[OrganizationSummary],
    summary="List affiliate organizations (admin)",
)
async def list_organizations(
    admin: AdminUser, db: DatabaseDep
) -> list[OrganizationSummary]:
    """List every affiliate organization with personnel + equipment counts."""
    rows = await db.fetch(f"select {_ORG_COLS} from public.organizations o order by o.name")
    return [OrganizationSummary.model_validate(dict(r)) for r in rows]


# A name to show for every member: accounts made before names were required
# have none, and a blank row cannot be picked.
_MEMBER_COLS = (
    "id, coalesce(nullif(btrim(full_name), ''), split_part(email, '@', 1), 'Member') "
    "as full_name, role::text as role, agency_type::text as agency_type, "
    "verified_percent, badge::text as badge"
)


@router.get(
    "/mine/members",
    response_model=list[OrganizationMember],
    summary="List the members of my organization (staff)",
)
async def list_my_members(user: StaffUser, db: DatabaseDep) -> list[OrganizationMember]:
    """The caller's own organization: captains first, then responders, by name.

    A staff account with no organization gets the staff of its agency that have
    none either, so the list is never just empty for a team set up by hand. An
    Admin belongs to no team and gets an empty list - Admin reads any roster
    through /organizations/{id}/personnel.
    """
    order = (
        "order by case role::text when 'sub_admin' then 0 else 1 end, "
        "full_name nulls last"
    )
    if user.primary_org_id is not None:
        rows = await db.fetch(
            f"select {_MEMBER_COLS} from public.users "
            f"where primary_org_id = $1 and role in ('sub_admin', 'response_team') {order}",
            user.primary_org_id,
        )
    elif user.agency_type is not None:
        rows = await db.fetch(
            f"select {_MEMBER_COLS} from public.users "
            "where primary_org_id is null and agency_type = $1::public.agency_type "
            f"and role in ('sub_admin', 'response_team') {order}",
            user.agency_type,
        )
    else:
        rows = []
    return [OrganizationMember.model_validate(dict(r)) for r in rows]


@router.get(
    "/{org_id}/personnel",
    response_model=list[OrganizationMember],
    summary="List an organization's personnel (admin)",
)
async def list_org_personnel(
    org_id: UUID, admin: AdminUser, db: DatabaseDep
) -> list[OrganizationMember]:
    """List the users assigned to an organization (its roster)."""
    exists = await db.fetchval("select 1 from public.organizations where id = $1", org_id)
    if exists is None:
        raise NotFoundError("Organization not found.")
    rows = await db.fetch(
        """
        select id, full_name, role::text as role, agency_type::text as agency_type,
               verified_percent, badge::text as badge
        from public.users
        where primary_org_id = $1
        order by
            case role::text
                when 'sub_admin' then 0
                when 'response_team' then 1
                else 2
            end,
            full_name nulls last
        """,
        org_id,
    )
    return [OrganizationMember.model_validate(dict(r)) for r in rows]
