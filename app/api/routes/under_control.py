"""Withdraw a fire's Under control (v1.12.49).

Declaring it is pressing FC-2 (app/api/routes/fire_codes.py); this takes it
back, for whoever may declare (app/services/under_control.py).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import DatabaseDep, StaffUser
from app.api.routes.incidents import finish_incident_change
from app.schemas.incident import IncidentDetail
from app.services import fire_broadcast, under_control
from app.services.alarm_notify import notify_under_control_withdrawn

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post(
    "/{incident_id}/under-control/withdraw",
    response_model=IncidentDetail,
    summary="Withdraw a fire's Under control",
)
async def withdraw_under_control(
    incident_id: UUID, request: Request, user: StaffUser, db: DatabaseDep
) -> IncidentDetail:
    """Fire Volunteer and BFP coordinators, and Admins who press fire codes."""
    await under_control.withdraw(db, request, user, incident_id)
    detail = await finish_incident_change(db, incident_id, "under_control_withdrawn")
    fire_broadcast.spawn(notify_under_control_withdrawn(db, incident_id, user.id))
    return detail
