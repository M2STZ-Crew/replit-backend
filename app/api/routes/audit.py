"""Audit log query endpoint (Phase 14, Section 7 #20).

Admin reads the whole record. A sub-admin reads the part of it about incidents
their agency can see — the Observer Console's History surface (v10 Section
2.6.1) is exactly that — with each entry's request IP and user agent withheld,
since those identify other people's devices rather than describe the incident.
Response Team and citizens have no audit view.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DatabaseDep, StaffUser
from app.core.exceptions import ForbiddenError
from app.schemas.audit import AuditLogResponse
from app.services.incident import visible_agencies

router = APIRouter(prefix="/audit-logs", tags=["audit"])

_COLS = (
    "l.id, l.actor_user_id, l.actor_role::text as actor_role, "
    "l.actor_agency::text as actor_agency, l.action, l.entity_type, l.entity_id, l.area_id, "
    "l.before_state, l.after_state, l.metadata, l.ip_address::text as ip_address, "
    "l.user_agent, l.request_id, l.created_at, a.designation as area_designation"
)


def _row_to_dict(row: Any, *, redact_device: bool) -> dict[str, Any]:
    """Parse the jsonb columns of an audit_logs row; drop device details if asked."""
    data = dict(row)
    for key in ("before_state", "after_state", "metadata"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = json.loads(value)
    if data.get("metadata") is None:
        data["metadata"] = {}
    if redact_device:
        data["ip_address"] = None
        data["user_agent"] = None
    return data


@router.get("", response_model=list[AuditLogResponse], summary="Query audit logs")
async def list_audit_logs(
    user: StaffUser,
    db: DatabaseDep,
    action: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    area_id: Annotated[UUID | None, Query()] = None,
    actor_user_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogResponse]:
    """List audit-log entries with optional filters, newest first.

    Admin: every entry. Sub-admin: entries tied to an incident visible to their
    agency. Response Team: refused.
    """
    if user.role not in ("admin", "sub_admin"):
        raise ForbiddenError("The action record is available to Admin and Sub-Admins only.")

    conditions: list[str] = []
    params: list[Any] = []
    agencies = visible_agencies(user)
    if agencies is not None:
        if not agencies:
            return []
        params.append(agencies)
        conditions.append(
            "l.area_id is not null and exists (select 1 from public.area_reports ar "
            "join public.reports r on r.id = ar.report_id "
            "where ar.area_id = l.area_id "
            f"and r.selected_agencies && ${len(params)}::public.agency_type[])"
        )
    if action is not None:
        params.append(action)
        conditions.append(f"l.action = ${len(params)}")
    if entity_type is not None:
        params.append(entity_type)
        conditions.append(f"l.entity_type = ${len(params)}")
    if area_id is not None:
        params.append(area_id)
        conditions.append(f"l.area_id = ${len(params)}")
    if actor_user_id is not None:
        params.append(actor_user_id)
        conditions.append(f"l.actor_user_id = ${len(params)}")

    params.append(limit)
    limit_pos = len(params)
    params.append(offset)
    offset_pos = len(params)

    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"select {_COLS} from public.audit_logs l "
        f"left join public.areas a on a.id = l.area_id {where_sql} "
        f"order by l.created_at desc limit ${limit_pos} offset ${offset_pos}",
        *params,
    )
    redact = user.role != "admin"
    return [
        AuditLogResponse.model_validate(_row_to_dict(r, redact_device=redact)) for r in rows
    ]
