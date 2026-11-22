"""Fire code endpoints (Phase 13, Section 7 #17-#18).

List the fire-code catalog, press a code (logged to fire_code_events and broadcast
to the incident channel), and read the per-incident press log. A code's target_role
(and optional target_agency) gates who may press it, and a responder only on a
fire they are on (app/services/fire_code_rules.py, v1.12.48).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DatabaseDep, StaffUser
from app.api.routes.incidents import finish_incident_change
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.realtime.manager import manager
from app.schemas.fire_code import (
    FireCodeEventResponse,
    FireCodePressRequest,
    FireCodeResponse,
)
from app.services.access import PRESS_CODES, admin_access
from app.services.fire_code_notify import notify_fire_code
from app.services.fire_code_rules import assert_responder_may_press
from app.services.incident import is_coordinator

log = get_logger(__name__)

router = APIRouter(prefix="/fire-codes", tags=["fire-codes"])

_CODE_COLS = (
    "id, code_number, name, description, target_role::text as target_role, "
    "target_agency::text as target_agency, is_active, display_order"
)
_EVENT_SELECT = (
    "select e.id, e.fire_code_id, fc.code_number, fc.name, e.area_id, "
    "e.pressed_by, e.pressed_at, e.notes, "
    "u.full_name as pressed_by_name, o.name as pressed_by_org "
    "from public.fire_code_events e "
    "join public.fire_codes fc on fc.id = e.fire_code_id "
    "left join public.users u on u.id = e.pressed_by "
    "left join public.organizations o on o.id = u.primary_org_id"
)


@router.get("", response_model=list[FireCodeResponse], summary="List fire codes")
async def list_fire_codes(user: CurrentUser, db: DatabaseDep) -> list[FireCodeResponse]:
    """List active fire codes in display order."""
    rows = await db.fetch(
        f"select {_CODE_COLS} from public.fire_codes where is_active order by display_order"
    )
    return [FireCodeResponse.model_validate(dict(r)) for r in rows]


@router.get(
    "/events",
    response_model=list[FireCodeEventResponse],
    summary="List fire-code press events",
)
async def list_fire_code_events(
    user: StaffUser,
    db: DatabaseDep,
    area_id: Annotated[UUID | None, Query()] = None,
) -> list[FireCodeEventResponse]:
    """List fire-code press events, optionally for one incident."""
    if area_id is not None:
        rows = await db.fetch(
            f"{_EVENT_SELECT} where e.area_id = $1 order by e.pressed_at desc", area_id
        )
    else:
        rows = await db.fetch(f"{_EVENT_SELECT} order by e.pressed_at desc limit 200")
    return [FireCodeEventResponse.model_validate(dict(r)) for r in rows]


@router.post(
    "/{code_id}/press",
    response_model=FireCodeEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Press a fire code",
)
async def press_fire_code(
    code_id: UUID, payload: FireCodePressRequest, user: StaffUser, db: DatabaseDep
) -> FireCodeEventResponse:
    """Log a fire-code press; gated by the code's target_role/target_agency."""
    code = await db.fetchrow(
        """
        select code_number, name, target_role::text as target_role,
               target_agency::text as target_agency, is_active
        from public.fire_codes
        where id = $1
        """,
        code_id,
    )
    if code is None:
        raise NotFoundError("Fire code not found.")
    if not code["is_active"]:
        raise BadRequestError("This fire code is inactive.")

    # Coordinators — admin, or a fire-agency sub-admin — may broadcast any code
    # ("Broadcast a fire code to all responding units"). A response_team user may
    # press only their own target code, on a fire they are on, and outside the
    # fire service only to call for help (v1.12.48). An observer sub-admin
    # (police, medical, barangay) may press none: fire codes direct the fire
    # response, and these agencies take part for awareness only.
    # An Admin presses from the console's incident page (v1.12.46): Fire
    # Volunteer, BFP, the central hub and the system Admin.
    access = admin_access(user)
    responder = access is None and user.role == "response_team"
    if access is not None:
        allowed = access.can(PRESS_CODES)
    elif responder:
        allowed = code["target_role"] == user.role and (
            code["target_agency"] is None or user.agency_type == code["target_agency"]
        )
    else:
        allowed = is_coordinator(user)
    if not allowed:
        raise ForbiddenError("You are not permitted to press this fire code.")

    if payload.area_id is not None:
        area_exists = await db.fetchval(
            "select 1 from public.areas where id = $1", payload.area_id
        )
        if area_exists is None:
            raise NotFoundError("Incident (area) not found.")
    if responder:
        await assert_responder_may_press(db, user, payload.area_id, code["code_number"])

    row = await db.fetchrow(
        """
        insert into public.fire_code_events (fire_code_id, area_id, pressed_by, notes)
        values ($1, $2, $3, $4)
        returning id, fire_code_id, area_id, pressed_by, pressed_at, notes
        """,
        code_id,
        payload.area_id,
        user.id,
        payload.notes,
    )
    assert row is not None
    data = dict(row)
    data["code_number"] = code["code_number"]
    data["name"] = code["name"]
    data["pressed_by_name"] = user.full_name
    data["pressed_by_org"] = user.org_name

    if payload.area_id is not None:
        await manager.broadcast(
            f"incident:{payload.area_id}",
            {
                "type": "fire_code_pressed",
                "area_id": str(payload.area_id),
                "code_number": code["code_number"],
                "name": code["name"],
                "pressed_by": str(user.id),
            },
        )
        # On the incident everywhere at once, and to the people the code is
        # for (v1.12.46). Best-effort: the press is saved either way.
        try:
            await finish_incident_change(db, payload.area_id, "fire_code_pressed")
        except Exception:
            log.error("fire_code_broadcast_failed", area_id=str(payload.area_id), exc_info=True)
        try:
            await notify_fire_code(
                db, payload.area_id, code["code_number"], code["name"], user.id
            )
        except Exception:
            log.error("fire_code_notify_failed", area_id=str(payload.area_id), exc_info=True)
    log.info(
        "fire_code_pressed",
        code_id=str(code_id),
        area_id=str(payload.area_id) if payload.area_id else None,
        by=str(user.id),
    )
    return FireCodeEventResponse.model_validate(data)