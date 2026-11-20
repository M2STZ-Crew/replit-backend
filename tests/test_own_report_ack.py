"""v1.12.44: a staff member's own report, and the central hub's acknowledgements.

19 Nov 2026: "there's an unexpected error when the coordinator report a fire
incident himself and he acknowledge it by himself too"; answered "Acknowledged
on sending". The error was the database refusing the central hub's Fire
Volunteer and medical members (the hub is filed under barangay); it is kept
now, organisation or not, and a coordinator's or responder's report starts
acknowledged by their organisation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import get_current_user, get_database, get_storage_client
from app.api.routes import reports
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import acknowledge
from app.services.acknowledge import OwnReportAck, acknowledge_own_report, insert_acceptance

_HUB = uuid4()
_AREA = uuid4()


def _staff(role: str, agency: str) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        role=role,
        agency_type=agency,
        primary_org_id=_HUB,
        org_agency_type="barangay",
        org_is_central_hub=True,
    )


class _Conn:
    """A connection whose acceptance insert the database refuses while
    [refuse_org] holds (an organisation of another agency)."""

    def __init__(self, answers: list[Any] | None = None, refuse_org: bool = False) -> None:
        self.answers = list(answers or [])
        self.refuse_org = refuse_org
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield self

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.answers.pop(0)

    async def execute(self, query: str, *args: Any) -> str:
        if "insert into public.area_acceptances" in query and self.refuse_org and args[3]:
            raise asyncpg.CheckViolationError(
                f"organization {args[3]} does not belong to agency {args[2]}"
            )
        self.executed.append((query, args))
        return "INSERT 0 1"


class _Db:
    def __init__(self, conn: _Conn, visible: bool = True) -> None:
        self.conn = conn
        self.visible = visible

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.visible

    @asynccontextmanager
    async def acquire(self) -> Any:
        yield self.conn


def _acceptances(conn: _Conn) -> list[tuple[Any, ...]]:
    return [a for q, a in conn.executed if "insert into public.area_acceptances" in q]


async def test_the_hubs_acknowledgement_is_kept_when_its_organisation_is_refused() -> None:
    conn = _Conn(refuse_org=True)
    user = _staff("sub_admin", "fire_volunteer")
    await insert_acceptance(conn, _AREA, user, "fire_volunteer", is_first=True)  # type: ignore[arg-type]
    (row,) = _acceptances(conn)
    assert row == (_AREA, user.id, "fire_volunteer", None, True)


async def test_once_the_database_allows_it_the_hub_is_credited() -> None:
    conn = _Conn()
    user = _staff("sub_admin", "medical")
    await insert_acceptance(conn, _AREA, user, "medical", is_first=False)  # type: ignore[arg-type]
    (row,) = _acceptances(conn)
    assert row == (_AREA, user.id, "medical", _HUB, False)


async def test_a_coordinators_report_verifies_its_fire() -> None:
    # Locked status, nobody acknowledged it yet, nobody first.
    conn = _Conn(["reported", False, False], refuse_org=True)
    user = _staff("sub_admin", "fire_volunteer")
    result = await acknowledge_own_report(_Db(conn), None, user, _AREA)  # type: ignore[arg-type]
    assert result == OwnReportAck(outcome="verified", before="reported")
    queries = [q for q, _ in conn.executed]
    assert any("set status = 'verified', verified_by = $2" in q for q in queries)
    assert _acceptances(conn) == [(_AREA, user.id, "fire_volunteer", None, True)]
    assert any("audit_logs" in q for q in queries)


async def test_a_coordinators_report_on_a_verified_fire_adds_their_agency() -> None:
    conn = _Conn(["verified", False])
    user = _staff("sub_admin", "medical")
    result = await acknowledge_own_report(_Db(conn), None, user, _AREA)  # type: ignore[arg-type]
    assert result == OwnReportAck(outcome="joined", before="verified")
    assert not any("set status" in q for q, _ in conn.executed)
    assert _acceptances(conn) == [(_AREA, user.id, "medical", _HUB, False)]


@pytest.mark.parametrize(
    ("user", "answers", "visible"),
    [
        # A responder's next act on a verified fire is responding.
        (_staff("response_team", "fire_volunteer"), ["verified", False], True),
        # Already acknowledged by them.
        (_staff("sub_admin", "bfp"), ["reported", True], True),
        # Out already.
        (_staff("sub_admin", "bfp"), ["fire_out"], True),
        # Their agency was not asked.
        (_staff("sub_admin", "police"), [], False),
        # A resident's report is checked by staff, never by itself.
        (AuthenticatedUser(id=uuid4(), role="general_user"), [], True),
    ],
)
async def test_what_a_staff_report_does_not_acknowledge(
    user: AuthenticatedUser, answers: list[Any], visible: bool
) -> None:
    conn = _Conn(answers)
    assert await acknowledge_own_report(_Db(conn, visible), None, user, _AREA) is None  # type: ignore[arg-type]
    assert _acceptances(conn) == []


# --------------------------------------------------------------------------- #
# The report route
# --------------------------------------------------------------------------- #
class _RouteDb:
    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "insert into public.reports" in query:
            return {"id": args[0], "created_at": datetime.now(UTC)}
        if "from public.areas" in query:
            return {
                "designation": "Near F. Victor Street",
                "centroid_lat": 14.54,
                "centroid_lng": 121.0,
                "report_count": 1,
            }
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "UPDATE"


class _Storage:
    async def upload(self, **_: Any) -> None:
        return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(("role", "acknowledged"), [("sub_admin", True), ("general_user", False)])
def test_the_report_says_whether_it_was_acknowledged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, role: str, acknowledged: bool
) -> None:
    user = AuthenticatedUser(
        id=uuid4(),
        role=role,
        agency_type="fire_volunteer" if role == "sub_admin" else None,
        verified_percent=60,
        phone_verified=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: _RouteDb()
    app.dependency_overrides[get_storage_client] = lambda: _Storage()
    finished: list[tuple[UUID, str, UUID | None]] = []

    async def _cluster(*_: Any, **__: Any) -> UUID:
        return _AREA

    async def _quiet(*_: Any, **__: Any) -> None:
        return None

    async def _ack(db: Any, request: Any, who: AuthenticatedUser, area: UUID) -> Any:
        return OwnReportAck("verified", "reported") if who.role == "sub_admin" else None

    async def _finish(db: Any, area: UUID, event: str, *, skip_reporter: UUID | None) -> None:
        finished.append((area, event, skip_reporter))

    monkeypatch.setattr(reports, "cluster_report", _cluster)
    monkeypatch.setattr(reports, "notify_area_neighbors", _quiet)
    monkeypatch.setattr(reports, "notify_staff_new_incident", _quiet)
    monkeypatch.setattr(reports, "acknowledge_own_report", _ack)
    monkeypatch.setattr(reports, "finish_incident_change", _finish)
    monkeypatch.setattr(reports, "_report_in_progress", _quiet)
    monkeypatch.setattr(reports.report_strikes, "assert_may_report", _quiet)

    buf = BytesIO()
    Image.new("RGB", (12, 8), "red").save(buf, format="PNG")
    response = client.post(
        "/reports/submit",
        data={"device_lat": "14.54", "device_lng": "121.0", "selected_agencies": "fire_volunteer"},
        files={"photo": ("fire.png", buf.getvalue(), "image/png")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["acknowledged"] is acknowledged
    if acknowledged:
        # Broadcast as an Accept is, without telling them what they just did.
        assert finished == [(_AREA, "incident_verified", user.id)]
    else:
        assert finished == []


def test_the_shared_insert_is_the_one_accept_uses() -> None:
    from app.api.routes import incidents

    assert incidents.insert_acceptance is acknowledge.insert_acceptance
