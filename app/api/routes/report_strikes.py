"""Prank-report strikes: a resident's standing and appeals, and the console's
review (v1.12.41; the ladder and its reasons are app/services/report_strikes.py).

Residents: GET /report-strikes/me, POST /report-strikes/me/{id}/appeal and
/lesson. A coordinator gives the everyday strike while rejecting a fire
(POST /incidents/{id}/reject with ``prank``); the central hub's Admins mark any
other report, check 3rd and 4th steps, and decide appeals here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import CurrentUser, DatabaseDep, StrikeReviewer
from app.core.exceptions import NotFoundError
from app.schemas.auth import AuthenticatedUser
from app.schemas.report_strike import (
    ReportingStanding,
    StrikeAppealDecision,
    StrikeAppealRequest,
    StrikeCheckRequest,
    StrikeGiveRequest,
    StrikeReviewItem,
    StrikeView,
)
from app.services import report_strikes as strikes
from app.services.audit import record_audit

router = APIRouter(prefix="/report-strikes", tags=["report strikes"])


def _view(strike: strikes.Strike, now: datetime) -> StrikeView:
    return StrikeView(
        id=strike.id,
        step=strike.step,
        status=strike.status,
        reason=strike.reason,
        given_at=strike.given_at,
        starts_at=strike.starts_at,
        pause_ends_at=strike.pause_ends_at(),
        verify_first_ends_at=strike.verify_first_ends_at(),
        expires_at=strike.expires_at,
        lesson_seen=strike.lesson_seen_at is not None,
        can_appeal=strike.can_appeal(now),
        appeal_state=strike.appeal_state(),
        appeal_text=strike.appeal_text,
        appeal_note=strike.appeal_note,
    )


def _item(item: dict[str, object], reviewer: AuthenticatedUser) -> StrikeReviewItem:
    return StrikeReviewItem.model_validate(
        {**item, "given_by_me": item.get("given_by") == reviewer.id}
    )


# --------------------------------------------------------------------------- #
# The resident
# --------------------------------------------------------------------------- #
@router.get(
    "/me",
    response_model=ReportingStanding,
    summary="Can I send reports, and if not, until when (residents)",
)
async def my_standing(user: CurrentUser, db: DatabaseDep) -> ReportingStanding:
    standing = await strikes.standing_of(db, user)
    lesson = standing.lesson_due
    return ReportingStanding(
        can_report=standing.can_report,
        removed=standing.removed,
        paused_until=standing.paused_until,
        verify_first_until=standing.verify_first_until,
        step=standing.step,
        lesson_due=lesson.id if lesson else None,
        strikes=[_view(s, standing.now) for s in standing.strikes],
    )


@router.post(
    "/me/{strike_id}/appeal",
    response_model=StrikeView,
    summary="Appeal one of my strikes (residents)",
)
async def appeal_my_strike(
    strike_id: UUID,
    payload: StrikeAppealRequest,
    request: Request,
    user: CurrentUser,
    db: DatabaseDep,
) -> StrikeView:
    async with db.acquire() as conn, conn.transaction():
        strike = await strikes.appeal(conn, strike_id=strike_id, user=user, text=payload.text)
        await record_audit(
            conn, request, user,
            action="report_strike.appeal", entity_type="report_strike",
            entity_id=strike.id, area_id=strike.area_id,
            metadata={"step": strike.step},
        )
    return _view(strike, datetime.now(UTC))


@router.post(
    "/me/{strike_id}/lesson",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="I read the lesson on what a false alarm costs (residents)",
)
async def my_lesson_read(strike_id: UUID, user: CurrentUser, db: DatabaseDep) -> Response:
    if not await strikes.lesson_seen(db, strike_id=strike_id, user=user):
        raise NotFoundError("Strike not found.", error_code="strike_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# The console
# --------------------------------------------------------------------------- #
@router.get(
    "",
    response_model=list[StrikeReviewItem],
    summary="Strikes to check, appeals to decide, or every strike (console)",
)
async def list_strikes(
    user: StrikeReviewer,
    db: DatabaseDep,
    view: Annotated[Literal["to_check", "appeals", "all"], Query()] = "to_check",
) -> list[StrikeReviewItem]:
    return [_item(item, user) for item in await strikes.review_queue(db, view)]


@router.post(
    "",
    response_model=StrikeReviewItem,
    status_code=status.HTTP_201_CREATED,
    summary="Mark a report a prank once its fire is rejected or a false alarm (console)",
)
async def mark_prank(
    payload: StrikeGiveRequest,
    request: Request,
    user: StrikeReviewer,
    db: DatabaseDep,
) -> StrikeReviewItem:
    async with db.acquire() as conn, conn.transaction():
        await strikes.assert_markable(conn, payload.report_id)
        strike = await strikes.give(
            conn,
            report_id=payload.report_id,
            reason=payload.reason,
            serious=payload.serious,
            giver=user,
        )
        await record_audit(
            conn, request, user,
            action="report_strike.give", entity_type="report_strike",
            entity_id=strike.id, area_id=strike.area_id,
            metadata={
                "step": strike.step,
                "serious": strike.serious,
                "awaiting_check": strike.status == "awaiting_confirmation",
            },
        )
    await strikes.tell(db, strike, "given")
    return _item(await strikes.review_item(db, strike.id), user)


async def _check(
    strike_id: UUID,
    payload: StrikeCheckRequest,
    request: Request,
    user: AuthenticatedUser,
    db: DatabaseDep,
    *,
    confirm: bool,
) -> StrikeReviewItem:
    async with db.acquire() as conn, conn.transaction():
        strike = await strikes.check(
            conn, strike_id=strike_id, reviewer=user, confirm=confirm, note=payload.note
        )
        await record_audit(
            conn, request, user,
            action="report_strike.confirm" if confirm else "report_strike.decline",
            entity_type="report_strike", entity_id=strike.id, area_id=strike.area_id,
            metadata={"step": strike.step},
        )
    await strikes.tell(db, strike, "confirmed" if confirm else "declined")
    return _item(await strikes.review_item(db, strike.id), user)


@router.post(
    "/{strike_id}/confirm",
    response_model=StrikeReviewItem,
    summary="Confirm a 3rd or 4th step, as the second staff member (console)",
)
async def confirm_strike(
    strike_id: UUID,
    payload: StrikeCheckRequest,
    request: Request,
    user: StrikeReviewer,
    db: DatabaseDep,
) -> StrikeReviewItem:
    return await _check(strike_id, payload, request, user, db, confirm=True)


@router.post(
    "/{strike_id}/decline",
    response_model=StrikeReviewItem,
    summary="Decline a 3rd or 4th step, as the second staff member (console)",
)
async def decline_strike(
    strike_id: UUID,
    payload: StrikeCheckRequest,
    request: Request,
    user: StrikeReviewer,
    db: DatabaseDep,
) -> StrikeReviewItem:
    return await _check(strike_id, payload, request, user, db, confirm=False)


@router.post(
    "/{strike_id}/appeal-decision",
    response_model=StrikeReviewItem,
    summary="Uphold or overturn a resident's appeal (console)",
)
async def decide_appeal(
    strike_id: UUID,
    payload: StrikeAppealDecision,
    request: Request,
    user: StrikeReviewer,
    db: DatabaseDep,
) -> StrikeReviewItem:
    overturn = payload.decision == "overturned"
    async with db.acquire() as conn, conn.transaction():
        strike = await strikes.decide_appeal(
            conn, strike_id=strike_id, reviewer=user, overturn=overturn, note=payload.note
        )
        await record_audit(
            conn, request, user,
            action=f"report_strike.appeal_{payload.decision}",
            entity_type="report_strike", entity_id=strike.id, area_id=strike.area_id,
            metadata={"step": strike.step},
        )
    await strikes.tell(db, strike, "overturned" if overturn else "upheld")
    return _item(await strikes.review_item(db, strike.id), user)
