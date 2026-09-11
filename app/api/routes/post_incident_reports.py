"""Post-Incident Report endpoints (v10 Section 2.5): file, read, list.

During a response, coordinators and responders capture only what is needed to
run it. The full record — truck, driver, roster, equipment taken — is filed here
once the fire is out, by the responding team captain, for everyone who went.

Fire out (POST /incidents/{id}/resolve) leaves the incident in
'post_incident_report'; filing is the only route to 'closed'. The form is
single-submit with no draft state: the report and the close commit together in
one transaction, and a database trigger refuses 'closed' without a report row.
Named "Post-Incident Report" throughout because ``audit_logs`` already means the
append-only action record.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Query, Request, status

from app.api.deps import DatabaseDep, StaffUser
from app.api.routes.incidents import finish_incident_change
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import Database
from app.schemas.post_incident_report import (
    PostIncidentReportCreate,
    PostIncidentReportResponse,
)
from app.services.audit import record_audit
from app.services.incident import (
    assert_incident_visible,
    assert_team_captain,
    assert_transition,
    visible_agencies,
    visible_area_sql,
)

log = get_logger(__name__)

router = APIRouter(tags=["post_incident_reports"])

_REPORT_SELECT = """
    select p.id, p.area_id, a.designation as area_designation, a.resolved_at,
           p.filed_by, p.filed_by_name, p.filed_by_role::text as filed_by_role,
           p.filed_by_agency::text as filed_by_agency,
           p.organization_id, o.name as organization_name,
           p.truck_equipment_id, p.truck_label, p.truck_type,
           p.driver_name, p.driver_user_id, p.roster, p.equipment_taken, p.notes,
           p.submitted_at
    from public.post_incident_reports p
    join public.areas a on a.id = p.area_id
    left join public.organizations o on o.id = p.organization_id
"""


def _to_response(row: Any) -> PostIncidentReportResponse:
    data = dict(row)
    if isinstance(data.get("roster"), str):
        data["roster"] = json.loads(data["roster"])
    data["equipment_taken"] = list(data.get("equipment_taken") or [])
    return PostIncidentReportResponse.model_validate(data)


async def _load_report(db: Database, incident_id: UUID) -> PostIncidentReportResponse | None:
    row = await db.fetchrow(f"{_REPORT_SELECT} where p.area_id = $1", incident_id)
    return _to_response(row) if row is not None else None


@router.post(
    "/incidents/{incident_id}/post-incident-report",
    response_model=PostIncidentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="File the Post-Incident Report and close the incident (team captain)",
)
async def file_post_incident_report(
    incident_id: UUID,
    payload: PostIncidentReportCreate,
    request: Request,
    user: StaffUser,
    db: DatabaseDep,
) -> PostIncidentReportResponse:
    """File once, fully filled; the incident moves post_incident_report -> closed."""
    assert_team_captain(user)
    await assert_incident_visible(db, incident_id, user)

    if payload.truck_equipment_id is not None:
        truck = await db.fetchval(
            "select 1 from public.equipment where id = $1", payload.truck_equipment_id
        )
        if truck is None:
            raise BadRequestError("That truck is not in the equipment register.")

    roster = [member.model_dump(mode="json") for member in payload.roster]
    async with db.acquire() as conn, conn.transaction():
        # Lock the area so two captains filing at once cannot both pass the check.
        current = await conn.fetchval(
            "select status::text from public.areas where id = $1 for update", incident_id
        )
        if current is None:
            raise NotFoundError("Incident not found.")
        assert_transition(str(current), "closed")
        try:
            report_id = await conn.fetchval(
                """
                insert into public.post_incident_reports
                    (area_id, filed_by, filed_by_name, filed_by_role, filed_by_agency,
                     organization_id, truck_equipment_id, truck_label, truck_type,
                     driver_name, driver_user_id, roster, equipment_taken, notes)
                values ($1, $2, $3, $4::public.user_role, $5::public.agency_type,
                        $6, $7, $8, $9, $10, $11, $12::jsonb, $13::text[], $14)
                returning id
                """,
                incident_id,
                user.id,
                user.full_name or user.email,
                user.role,
                user.agency_type,
                user.primary_org_id,
                payload.truck_equipment_id,
                payload.truck_label,
                payload.truck_type,
                payload.driver_name,
                payload.driver_user_id,
                json.dumps(roster),
                payload.equipment_taken,
                payload.notes,
            )
        except asyncpg.UniqueViolationError as exc:
            raise ConflictError(
                "A Post-Incident Report has already been filed for this incident."
            ) from exc
        await conn.execute(
            "update public.areas set status = 'closed', closed_by = $2 where id = $1",
            incident_id,
            user.id,
        )
        await record_audit(
            conn,
            request,
            user,
            action="incident.post_incident_report",
            entity_type="post_incident_report",
            entity_id=report_id,
            area_id=incident_id,
            before_state={"status": str(current)},
            after_state={
                "status": "closed",
                "truck_label": payload.truck_label,
                "truck_type": payload.truck_type,
                "driver_name": payload.driver_name,
                "roster_count": len(roster),
                "equipment_count": len(payload.equipment_taken),
            },
        )

    log.info(
        "post_incident_report_filed",
        incident_id=str(incident_id),
        report_id=str(report_id),
        user_id=str(user.id),
    )
    await finish_incident_change(db, incident_id, "incident_closed")
    report = await _load_report(db, incident_id)
    assert report is not None
    return report


@router.get(
    "/incidents/{incident_id}/post-incident-report",
    response_model=PostIncidentReportResponse,
    summary="Read an incident's Post-Incident Report",
)
async def get_post_incident_report(
    incident_id: UUID, user: StaffUser, db: DatabaseDep
) -> PostIncidentReportResponse:
    """The filed report for one incident; 404 while it is still owed."""
    await assert_incident_visible(db, incident_id, user)
    report = await _load_report(db, incident_id)
    if report is None:
        raise NotFoundError("No Post-Incident Report has been filed for this incident yet.")
    return report


@router.get(
    "/post-incident-reports",
    response_model=list[PostIncidentReportResponse],
    summary="List Post-Incident Reports visible to me",
)
async def list_post_incident_reports(
    user: StaffUser,
    db: DatabaseDep,
    area_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PostIncidentReportResponse]:
    """Filed reports, newest first, scoped by agency visibility (admin: all)."""
    agencies = visible_agencies(user)
    if agencies is not None and not agencies:
        return []
    conditions: list[str] = []
    params: list[Any] = []
    if agencies is not None:
        params.append(agencies)
        conditions.append(visible_area_sql(len(params)))
    if area_id is not None:
        params.append(area_id)
        conditions.append(f"p.area_id = ${len(params)}")
    params.append(limit)
    limit_pos = len(params)
    params.append(offset)
    offset_pos = len(params)
    where_sql = f"where {' and '.join(conditions)}" if conditions else ""
    rows = await db.fetch(
        f"{_REPORT_SELECT} {where_sql} "
        f"order by p.submitted_at desc limit ${limit_pos} offset ${offset_pos}",
        *params,
    )
    return [_to_response(r) for r in rows]
