"""v1.12.48: who may press a fire code, and where.

22 Nov 2026, answered "Coordinators declare": responders press only on fires
they are on; crews outside the fire service only call for help (FC-7, FC-8).
Before, any responder of any agency could press any code on any fire.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import fire_codes
from app.main import app
from app.schemas.auth import AuthenticatedUser

AREA = uuid4()
EVERY_CODE = [f"FC-{n}" for n in range(1, 9)]


class _Db:
    """One code, and the presser's responses on the incident."""

    def __init__(self, code: str, responses: list[str]) -> None:
        self.code = code
        self.responses = responses
        self.saved: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.fire_codes" in query:
            return {
                "code_number": self.code, "name": "A code", "target_role": "response_team",
                "target_agency": None, "is_active": True,
            }
        if "insert into public.fire_code_events" in query:
            self.saved.append(args)
            return {
                "id": uuid4(), "fire_code_id": args[0], "area_id": args[1],
                "pressed_by": args[2], "pressed_at": datetime.now(UTC), "notes": args[3],
            }
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "d.organization_id = $3" in query:
            return getattr(self, "going", True)  # the presser's organization is going
        if "dispatch_logs" in query:
            return any(status in args[2] for status in self.responses)
        return 1  # the incident exists


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def _quiet(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(fire_codes, "finish_incident_change", _quiet)
    monkeypatch.setattr(fire_codes, "notify_fire_code", _quiet)
    monkeypatch.setattr(fire_codes.manager, "broadcast", _quiet)
    # Declaring with FC-2 is tests/test_alarm_status.py's (v1.12.49).
    monkeypatch.setattr(fire_codes, "UNDER_CONTROL_CODE", "not in these tests")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _press(
    client: TestClient,
    code: str,
    *,
    role: str = "response_team",
    agency: str = "bfp",
    responses: tuple[str, ...] = ("active",),
    area: UUID | None = AREA,
) -> tuple[int, _Db]:
    db = _Db(code, list(responses))
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=uuid4(), role=role, agency_type=agency, full_name="Ana Cruz"
    )
    body = {"area_id": str(area)} if area else {}
    return client.post(f"/fire-codes/{uuid4()}/press", json=body).status_code, db


@pytest.mark.parametrize("agency", ["bfp", "fire_volunteer"])
@pytest.mark.parametrize("code", EVERY_CODE)
def test_a_fire_crew_on_it_presses_every_code(client: TestClient, agency: str, code: str) -> None:
    status, db = _press(client, code, agency=agency)
    assert status == 201
    assert len(db.saved) == 1


@pytest.mark.parametrize("agency", ["police", "medical", "barangay"])
@pytest.mark.parametrize("code", EVERY_CODE)
def test_another_crew_only_calls_for_help(client: TestClient, agency: str, code: str) -> None:
    status, db = _press(client, code, agency=agency)
    allowed = code in ("FC-7", "FC-8")
    assert status == (201 if allowed else 403)
    assert len(db.saved) == (1 if allowed else 0)


@pytest.mark.parametrize("code", EVERY_CODE)
@pytest.mark.parametrize("responses", [(), ("withdrawn",)])
def test_nobody_presses_on_a_fire_they_are_not_on(
    client: TestClient, code: str, responses: tuple[str, ...]
) -> None:
    status, db = _press(client, code, responses=responses)
    assert status == 403
    assert db.saved == []


@pytest.mark.parametrize("code", EVERY_CODE)
def test_after_fire_out_a_fire_crew_overhauls_and_returns(client: TestClient, code: str) -> None:
    status, _ = _press(client, code, responses=("completed",))
    assert status == (201 if code in ("FC-4", "FC-5") else 403)


def test_a_responder_always_names_the_fire(client: TestClient) -> None:
    status, db = _press(client, "FC-6", area=None)
    assert status == 403
    assert db.saved == []


@pytest.mark.parametrize("agency", ["bfp", "fire_volunteer"])
@pytest.mark.parametrize("code", ["FC-2", "FC-6"])
def test_a_fire_coordinator_presses_without_going(
    client: TestClient, agency: str, code: str
) -> None:
    status, _ = _press(client, code, role="sub_admin", agency=agency, responses=())
    assert status == 201
