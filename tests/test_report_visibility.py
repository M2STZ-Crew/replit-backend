"""Post-Incident Reports are for the people who responded (hermetic).

What these pin:
- someone who responded, or a captain whose team responded or filed, may read
  an incident's reports; another firefighter who can see the incident may not;
  Admin always may;
- the reports list and the AI summaries list carry the same rule for anyone
  but Admin, with the caller's own id, team and captaincy as the parameters.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api.routes import post_incident_reports as pir
from app.core.exceptions import ForbiddenError
from app.schemas.auth import AuthenticatedUser
from app.services import ai_summary
from app.services.incident import assert_responded, responded_params

AREA = uuid4()
ORG = uuid4()


def _user(
    role: str, agency: str | None = "fire_volunteer", org: UUID | None = ORG
) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency, primary_org_id=org)


class _Db:
    """Answers the responded check, and records what was asked."""

    def __init__(self, responded: bool) -> None:
        self.responded = responded
        self.asked: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.asked.append((query, args))
        if "public.dispatch_logs d" in query:
            return self.responded
        if "status::text from public.areas" in query:
            return "closed"
        return True  # visible to the caller's agency

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.asked.append((query, args))
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.asked.append((query, args))
        return None


async def test_someone_who_responded_may_read() -> None:
    db = _Db(responded=True)
    await assert_responded(db, AREA, _user("response_team"))  # type: ignore[arg-type]


async def test_another_firefighter_may_not() -> None:
    with pytest.raises(ForbiddenError) as caught:
        await assert_responded(_Db(responded=False), AREA, _user("response_team"))  # type: ignore[arg-type]
    assert "responded" in caught.value.message


async def test_admin_always_may_and_is_not_asked() -> None:
    db = _Db(responded=False)
    await assert_responded(db, AREA, _user("admin", None, None))  # type: ignore[arg-type]
    assert db.asked == []


def test_a_captain_counts_their_team_a_responder_only_themselves() -> None:
    captain = _user("sub_admin", "bfp")
    responder = _user("response_team")
    assert responded_params(captain) == (captain.id, ORG, True)
    assert responded_params(responder) == (responder.id, ORG, False)
    lone = _user("sub_admin", "fire_volunteer", None)
    assert responded_params(lone) == (lone.id, lone.id, True), "no org: the captain's own"


async def test_reading_one_incidents_reports_needs_to_have_responded() -> None:
    db = _Db(responded=False)
    with pytest.raises(ForbiddenError):
        await pir.list_incident_post_incident_reports(AREA, _user("sub_admin"), db)  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await pir.get_post_incident_report(AREA, _user("sub_admin"), db)  # type: ignore[arg-type]


async def test_the_reports_list_keeps_to_incidents_the_caller_responded_to() -> None:
    user = _user("response_team")
    db = _Db(responded=True)
    await pir.list_post_incident_reports(user, db, area_id=None, limit=50, offset=0)  # type: ignore[arg-type]
    query, args = db.asked[-1]
    assert "public.dispatch_logs d" in query
    assert (user.id, ORG, False) == tuple(args[1:4])

    admin_db = _Db(responded=False)
    admin = _user("admin", None, None)
    await pir.list_post_incident_reports(admin, admin_db, area_id=None, limit=50, offset=0)  # type: ignore[arg-type]
    assert "dispatch_logs" not in admin_db.asked[-1][0], "Admin sees every report"


async def test_the_summaries_list_does_too() -> None:
    db = _Db(responded=True)
    captain = _user("sub_admin")
    await ai_summary.list_summarized_incidents(
        db,  # type: ignore[arg-type]
        ["fire_volunteer", "bfp"],
        limit=10,
        responder=responded_params(captain),
    )
    query, args = db.asked[-1]
    assert "public.dispatch_logs d" in query
    assert tuple(args[2:5]) == (captain.id, ORG, True)
