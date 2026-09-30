"""One Post-Incident Report per responding team (hermetic).

A fire is often fought by more than one team, and an incident used to hold a
single report: whoever filed first closed it and the other teams' units, crews
and equipment were never recorded. Now each team's captain files their own. The
first report closes the incident; the others are added to it; no team files
twice; and each captain's tray lists what their own team still owes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import post_incident_reports
from app.main import app
from app.schemas.auth import AuthenticatedUser

_AREA = uuid4()
_HERCULES, _BFP = uuid4(), uuid4()
_NOW = datetime(2026, 9, 30, 8, 40, tzinfo=UTC)

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20261001090000_pir_one_per_team.sql"
).read_text(encoding="utf-8")


def _captain(org: UUID | None, agency: str = "fire_volunteer") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type=agency, primary_org_id=org,
        full_name="Captain",
    )


class _State:
    """One incident as the database holds it."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.teams: list[UUID] = []  # who has filed, in order
        self.closes = 0


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Conn:
    def __init__(self, state: _State) -> None:
        self.s = state

    def transaction(self) -> _Tx:
        return _Tx()

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        if "for update" in q:
            return self.s.status
        if q.startswith("select 1 from public.post_incident_reports p"):
            return 1 if args[1] in self.s.teams else None
        if "insert into public.post_incident_reports" in q:
            self.s.teams.append(args[5] or args[1])  # organization_id, else filed_by
            return uuid4()
        return None

    async def execute(self, query: str, *args: Any) -> str:
        if "set status = 'closed'" in query:
            self.s.status = "closed"
            self.s.closes += 1
        return "OK"


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Db:
    def __init__(self, state: _State) -> None:
        self.s = state
        self.fetches: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> _Acquire:
        return _Acquire(_Conn(self.s))

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        if q.startswith("select status::text from public.areas"):
            return self.s.status
        return True  # visible to the caller's agency

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if q.startswith("select reported_at, resolved_at"):
            return {"reported_at": _NOW, "resolved_at": _NOW}
        if "from public.post_incident_reports p" in q:
            team = args[1]
            return _row(team) if team in self.s.teams else None
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetches.append((" ".join(query.split()), args))
        if "from public.post_incident_reports p" in query:
            return [_row(t) for t in self.s.teams]
        return []


def _row(team: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(), "area_id": _AREA, "area_designation": "Area 24", "resolved_at": _NOW,
        "incident_at": _NOW, "fire_out_at": _NOW, "filed_by": uuid4(),
        "filed_by_name": "Captain", "filed_by_role": "sub_admin",
        "filed_by_agency": "fire_volunteer", "organization_id": team,
        "organization_name": "Team", "units": '[{"name": "Apollo"}]',
        "truck_equipment_id": None, "truck_label": "Apollo", "truck_type": "Unit",
        "driver_name": "Marco Santos", "driver_user_id": None,
        "roster": '[{"name": "Marco Santos"}]', "equipment_taken": ["Hose line"],
        "notes": None, "false_alarm": False, "false_alarm_note": None, "submitted_at": _NOW,
    }


_BODY = {
    "units": [{"name": "Apollo", "type": "Fire Truck"}],
    "driver_name": "Marco Santos",
    "roster": [{"name": "Marco Santos"}],
    "equipment_taken": ["Hose line"],
}


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What was announced after each filing, in place of the real broadcast."""
    seen: list[str] = []

    async def _finish(_db: Any, _incident: UUID, event: str) -> None:
        seen.append(event)

    async def _summarize(_incident: UUID) -> None:
        seen.append("summary_scheduled")

    async def _audit(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(post_incident_reports, "finish_incident_change", _finish)
    monkeypatch.setattr(post_incident_reports, "summarize_in_background", _summarize)
    monkeypatch.setattr(post_incident_reports, "record_audit", _audit)
    return seen


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(user: AuthenticatedUser, db: _Db) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db


def _file(client: TestClient) -> Any:
    return client.post(f"/incidents/{_AREA}/post-incident-report", json=_BODY)


# ---------------------------------------------------------------- filing ---
def test_the_first_report_closes_the_incident(client: TestClient, events: list[str]) -> None:
    state = _State("post_incident_report")
    _as(_captain(_HERCULES), _Db(state))

    assert _file(client).status_code == 201
    assert state.status == "closed" and state.closes == 1
    assert state.teams == [_HERCULES]
    assert events == ["incident_closed", "summary_scheduled"]


def test_a_second_team_adds_its_report_to_the_closed_incident(
    client: TestClient, events: list[str]
) -> None:
    state = _State("post_incident_report")
    db = _Db(state)
    _as(_captain(_HERCULES), db)
    assert _file(client).status_code == 201
    _as(_captain(_BFP, "bfp"), db)

    response = _file(client)

    assert response.status_code == 201, response.text
    assert state.teams == [_HERCULES, _BFP]
    assert state.closes == 1, "only the first report closes it"
    # The summary is rewritten, so it now covers both teams.
    assert events[-2:] == ["post_incident_report_added", "summary_scheduled"]
    assert response.json()["organization_id"] == str(_BFP)


def test_a_team_cannot_file_twice(client: TestClient, events: list[str]) -> None:
    state = _State("post_incident_report")
    db = _Db(state)
    _as(_captain(_HERCULES), db)
    assert _file(client).status_code == 201
    # Another captain of the same organisation.
    _as(_captain(_HERCULES), db)

    response = _file(client)

    assert response.status_code == 409
    assert "already filed" in response.json()["message"]
    assert state.teams == [_HERCULES]


def test_two_captains_with_no_organisation_are_two_teams(
    client: TestClient, events: list[str]
) -> None:
    state = _State("post_incident_report")
    db = _Db(state)
    for _ in range(2):
        _as(_captain(None), db)
        assert _file(client).status_code == 201
    assert len(state.teams) == 2


def test_a_live_incident_still_cannot_be_reported_on(
    client: TestClient, events: list[str]
) -> None:
    state = _State("en_route")
    _as(_captain(_HERCULES), _Db(state))
    assert _file(client).status_code == 409
    assert state.teams == []


# --------------------------------------------------------------- reading ---
def test_every_teams_report_is_listed_for_the_incident(client: TestClient) -> None:
    state = _State("closed")
    state.teams = [_HERCULES, _BFP]
    _as(_captain(_BFP, "bfp"), _Db(state))

    listed = client.get(f"/incidents/{_AREA}/post-incident-reports")
    mine = client.get(f"/incidents/{_AREA}/post-incident-report")

    assert listed.status_code == 200
    assert [r["organization_id"] for r in listed.json()] == [str(_HERCULES), str(_BFP)]
    # The single-report route gives a captain their own team's.
    assert mine.json()["organization_id"] == str(_BFP)


def test_the_tray_is_what_my_team_still_owes(client: TestClient) -> None:
    captain = _captain(_BFP, "bfp")
    db = _Db(_State("closed"))
    _as(captain, db)

    assert client.get("/post-incident-reports/owed").status_code == 200

    query, args = db.fetches[0]
    # Nobody has filed: anyone who can see it may. Closed by another team: only
    # a team that actually responded still owes one. Never one already filed.
    assert "a.status = 'post_incident_report'" in query
    assert "a.status = 'closed' and exists ( select 1 from public.dispatch_logs d" in query
    assert "d.status <> 'withdrawn'" in query
    assert "not exists ( select 1 from public.post_incident_reports p" in query
    assert args == (["fire_volunteer", "bfp"], _BFP, captain.id)


@pytest.mark.parametrize(
    "user",
    [
        AuthenticatedUser(id=uuid4(), role="response_team", agency_type="fire_volunteer"),
        AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="police"),
        AuthenticatedUser(id=uuid4(), role="admin"),
    ],
)
def test_only_a_team_captain_owes_a_report(client: TestClient, user: AuthenticatedUser) -> None:
    db = _Db(_State("post_incident_report"))
    _as(user, db)
    response = client.get("/post-incident-reports/owed")
    assert response.status_code == 200 and response.json() == []
    assert db.fetches == []


# -------------------------------------------------------------- database ---
def test_the_migration_replaces_one_per_incident_with_one_per_team() -> None:
    sql = " ".join(_MIGRATION.split())
    assert "drop constraint if exists post_incident_reports_area_id_key" in sql
    assert (
        "create unique index if not exists post_incident_reports_one_per_team_idx "
        "on public.post_incident_reports (area_id, coalesce(organization_id, filed_by))"
    ) in sql
    # The route's team expression must be the index's, or the check and the
    # constraint would disagree about what a team is.
    assert post_incident_reports._TEAM_SQL == "coalesce(p.organization_id, p.filed_by)"
