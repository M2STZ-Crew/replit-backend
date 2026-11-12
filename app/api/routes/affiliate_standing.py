"""Suspend, revoke, restore or delete an affiliate organisation (v1.12.28).

12 November 2026: "affiliate management (freeze account, or soft delete, or
hard delete, for revoked reasons)". The reviewers of affiliates — the system
Admin and the central hub — may:

- **Suspend** (freeze): nobody of the organisation signs in or acts until it
  is restored (app/api/deps.py refuses them, ``organization_suspended``).
  Restore undoes it at any time.
- **Revoke** (soft delete): the same, and it leaves the network; its records
  stay. Restore undoes it for [RESTORE_DAYS] days.
- **Delete permanently**: only an organisation with no incidents on record —
  nothing acknowledged, responded to, routed, filed or reported by it. Its
  accounts and the organisation are removed for good. The name is typed out
  to confirm.

Each needs a reason (misconduct, inactive, duplicate, fraudulent application,
the organisation's own request, or other, which needs a note) and goes to the
audit log. The central hub, and the reviewer's own organisation, are not
offered: either would lock its reviewers out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import AffiliateReviewer, AuthClientDep, DatabaseDep
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.supabase_auth import AuthError
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import (
    OrganizationDelete,
    OrganizationDeleted,
    OrganizationSummary,
    StandingChange,
    StandingRestore,
)
from app.services.audit import record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/affiliates/organizations", tags=["affiliates"])

RESTORE_DAYS = 30
RESTORE_WINDOW = timedelta(days=RESTORE_DAYS)

REASON_LABELS = {
    "misconduct": "Misconduct",
    "inactive": "Inactive",
    "duplicate": "Duplicate",
    "fraudulent_application": "Fraudulent application",
    "organization_request": "The organization's request",
    "other": "Other",
}


async def _locked(conn: Any, org_id: UUID) -> dict[str, Any]:
    """The organisation, locked for the change; 404 when there is none."""
    row = await conn.fetchrow(
        """
        select o.id, o.name,
               coalesce(to_jsonb(o) ->> 'standing', 'active') as standing,
               (to_jsonb(o) ->> 'standing_changed_at')::timestamptz as standing_changed_at,
               coalesce((to_jsonb(o) ->> 'is_central_hub')::boolean, false) as is_central_hub
          from public.organizations o
         where o.id = $1
         for update
        """,
        org_id,
    )
    if row is None:
        raise NotFoundError("Organization not found.")
    return dict(row)


def _guard(user: AuthenticatedUser, org: dict[str, Any]) -> None:
    if org["is_central_hub"]:
        raise ConflictError(
            "The central hub cannot be suspended, revoked or deleted.",
            error_code="central_hub",
        )
    if user.primary_org_id is not None and org["id"] == user.primary_org_id:
        raise ConflictError(
            "You cannot suspend, revoke or delete your own organization.",
            error_code="own_organization",
        )


def _note(reason: str, note: str | None) -> str | None:
    note = (note or "").strip() or None
    if reason == "other" and note is None:
        raise BadRequestError(
            "Say why: a note is needed when the reason is Other.",
            error_code="note_required",
            details={"field": "note"},
        )
    return note


async def _summary(db: Database, org_id: UUID) -> OrganizationSummary:
    from app.api.routes.organizations import _ORG_COLS

    row = await db.fetchrow(
        f"select {_ORG_COLS} from public.organizations o where o.id = $1", org_id
    )
    if row is None:
        raise NotFoundError("Organization not found.")
    return OrganizationSummary.model_validate(dict(row))


async def _set_standing(
    db: Database,
    request: Request,
    user: AuthenticatedUser,
    org_id: UUID,
    *,
    to: str,
    reason: str | None,
    note: str | None,
    allowed_from: tuple[str, ...],
) -> OrganizationSummary:
    async with db.acquire() as conn, conn.transaction():
        org = await _locked(conn, org_id)
        _guard(user, org)
        current = org["standing"]
        if current == to:
            raise ConflictError(f"{org['name']} is already {to}.", error_code=f"already_{to}")
        if current not in allowed_from:
            raise ConflictError(
                f"{org['name']} is {current}: restore it first.",
                error_code="restore_first",
                details={"standing": current},
            )
        if to == "active" and current == "revoked":
            changed = org["standing_changed_at"]
            if changed is not None and changed + RESTORE_WINDOW < await conn.fetchval(
                "select now()"
            ):
                raise ConflictError(
                    f"{org['name']} was revoked more than {RESTORE_DAYS} days ago and "
                    "can no longer be restored. It can apply again.",
                    error_code="restore_window_passed",
                )
        await conn.execute(
            """
            update public.organizations
               set standing = $2,
                   standing_reason = $3,
                   standing_note = $4,
                   standing_changed_at = now(),
                   standing_changed_by = $5,
                   is_active = ($2 = 'active'),
                   updated_at = now()
             where id = $1
            """,
            org_id,
            to,
            reason,
            note,
            user.id,
        )
        await record_audit(
            conn,
            request,
            user,
            action={"suspended": "affiliate.suspend", "revoked": "affiliate.revoke"}.get(
                to, "affiliate.restore"
            ),
            entity_type="organization",
            entity_id=org_id,
            before_state={"standing": current},
            after_state={"standing": to},
            metadata={"reason": reason, "note": note, "organization": org["name"]},
        )
    log.info(
        "affiliate_standing_changed",
        organization_id=str(org_id),
        standing=to,
        reason=reason,
        user_id=str(user.id),
    )
    return await _summary(db, org_id)


@router.post(
    "/{org_id}/suspend",
    response_model=OrganizationSummary,
    summary="Suspend (freeze) an affiliate organization",
)
async def suspend_organization(
    org_id: UUID,
    payload: StandingChange,
    request: Request,
    user: AffiliateReviewer,
    db: DatabaseDep,
) -> OrganizationSummary:
    """Freeze it: nobody of it signs in or acts until Restore."""
    note = _note(payload.reason, payload.note)
    return await _set_standing(
        db,
        request,
        user,
        org_id,
        to="suspended",
        reason=payload.reason,
        note=note,
        allowed_from=("active",),
    )


@router.post(
    "/{org_id}/revoke",
    response_model=OrganizationSummary,
    summary="Revoke (soft-delete) an affiliate organization; restorable for 30 days",
)
async def revoke_organization(
    org_id: UUID,
    payload: StandingChange,
    request: Request,
    user: AffiliateReviewer,
    db: DatabaseDep,
) -> OrganizationSummary:
    """Take it off the network, frozen, its records kept; Restore for 30 days."""
    note = _note(payload.reason, payload.note)
    return await _set_standing(
        db,
        request,
        user,
        org_id,
        to="revoked",
        reason=payload.reason,
        note=note,
        allowed_from=("active", "suspended"),
    )


@router.post(
    "/{org_id}/restore",
    response_model=OrganizationSummary,
    summary="Restore a suspended organization, or one revoked in the last 30 days",
)
async def restore_organization(
    org_id: UUID,
    payload: StandingRestore,
    request: Request,
    user: AffiliateReviewer,
    db: DatabaseDep,
) -> OrganizationSummary:
    """Back to active: its people sign in and act again."""
    note = (payload.note or "").strip() or None
    return await _set_standing(
        db,
        request,
        user,
        org_id,
        to="active",
        reason=None,
        note=note,
        allowed_from=("suspended", "revoked"),
    )


async def incidents_on_record(db: Any, org_id: UUID) -> int:
    """Everything an organisation did on an incident: acknowledged, responded
    to, was routed, filed a report on, or a member reported."""
    count = await db.fetchval(
        """
        select (select count(*) from public.area_acceptances x where x.organization_id = $1)
             + (select count(*) from public.dispatch_logs d where d.organization_id = $1)
             + (select count(*) from public.area_routes rt where rt.organization_id = $1)
             + (select count(*) from public.post_incident_reports p where p.organization_id = $1)
             + (select count(*) from public.reports r
                  join public.users u on u.id = r.reporter_id
                 where u.primary_org_id = $1)
        """,
        org_id,
    )
    return int(count or 0)


@router.post(
    "/{org_id}/delete",
    response_model=OrganizationDeleted,
    summary="Delete an affiliate organization permanently (only with no incidents on record)",
)
async def delete_organization(
    org_id: UUID,
    payload: OrganizationDelete,
    request: Request,
    user: AffiliateReviewer,
    db: DatabaseDep,
    auth: AuthClientDep,
) -> OrganizationDeleted:
    """Remove the organisation and every account of it, for good.

    Refused (409 ``has_incidents``) when it has any incident on record: revoke
    it instead, which keeps the record. The name must be typed to confirm.
    """
    note = _note(payload.reason, payload.note)
    async with db.acquire() as conn, conn.transaction():
        org = await _locked(conn, org_id)
        _guard(user, org)
    if payload.confirm_name.strip().casefold() != str(org["name"]).strip().casefold():
        raise BadRequestError(
            "Type the organization's name exactly to delete it.",
            error_code="name_mismatch",
            details={"field": "confirm_name"},
        )
    on_record = await incidents_on_record(db, org_id)
    if on_record:
        raise ConflictError(
            f"{org['name']} has {on_record} incident record(s), so it cannot be deleted. "
            "Revoke it instead: that keeps the record.",
            error_code="has_incidents",
            details={"incidents_on_record": on_record},
        )
    members = await db.fetch("select id from public.users where primary_org_id = $1", org_id)
    deleted = 0
    for member in members:
        try:
            await auth.admin_delete_user(user_id=str(member["id"]))
        except AuthError as exc:
            log.error("affiliate_delete_account_failed", user_id=str(member["id"]))
            raise ExternalServiceError(
                f"{deleted} of {len(members)} accounts were deleted before one could not "
                "be. Nothing else was removed; try again.",
                error_code="account_delete_failed",
            ) from exc
        deleted += 1
    await db.execute("delete from public.organizations where id = $1", org_id)
    await record_audit(
        db,
        request,
        user,
        action="affiliate.delete",
        entity_type="organization",
        entity_id=org_id,
        before_state={"standing": org["standing"], "accounts": len(members)},
        after_state={"deleted": True},
        metadata={"reason": payload.reason, "note": note, "organization": org["name"]},
    )
    log.info(
        "affiliate_deleted",
        organization_id=str(org_id),
        accounts=deleted,
        reason=payload.reason,
        user_id=str(user.id),
    )
    return OrganizationDeleted(id=org_id, name=org["name"], accounts_deleted=deleted)
