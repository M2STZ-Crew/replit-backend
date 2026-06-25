"""Audit log query endpoint (Phase 14, Section 7 #20) — admin only."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DatabaseDep
from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit"])

_COLS = (
    "id, actor_user_id, actor_role::text as actor_role, "
    "actor_agency::text as actor_agency, action, entity_type, entity_id, area_id, "
    "before_state, after_state, metadata, ip_address::text as ip_address, "
    "user_agent, request_id, created_at"
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Parse the jsonb columns of an audit_logs row."""
    data = dict(row)
    for key in ("before_state", "after_state", "metadata"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = json.loads(value)
    if data.get("metadata") is None:
        data["metadata"] = {}
    return data


@router.get("", response_model=list[AuditLogResponse], summary="Query audit logs (admin)")
async def list_audit_logs(
    admin: AdminUser,
    db: DatabaseDep,
    action: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    area_id: Annotated[UUID | None, Query()] = None,
    actor_user_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogResponse]:
    """List audit-log entries with optional filters, newest first (admin)."""
    conditions: list[str] = []
    params: list[Any] = []
    if action is not None:
        params.append(action)
        conditions.append(f"action = ${len(params)}")
    if entity_type is not None:
        params.append(entity_type)
        conditions.append(f"entity_type = ${len(params)}")
    if area_id is not None:
        params.append(area_id)
        conditions.append(f"area_id = ${len(params)}")
    if actor_user_id is not None:
        params.append(actor_user_id)
        conditions.append(f"actor_user_id = ${len(params)}")

    params.append(limit)
    limit_pos = len(params)
    params.append(offset)
    offset_pos = len(params)

    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"select {_COLS} from public.audit_logs {where_sql} "
        f"order by created_at desc limit ${limit_pos} offset ${offset_pos}",
        *params,
    )
    return [AuditLogResponse.model_validate(_row_to_dict(r)) for r in rows]