"""v1.12.46: a fire code is shown and heard; hydrants verified by a field check.

20 Nov 2026: "if they press the fire code, there's nothing happening".
Answered: show it and alert, by what the code asks; Admins press from the
console too. And "make all of the fire hydrants as unverified and make it
color gray. if it's verified make it the default color": verified by a field
check, for 6 months.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import fire_codes, map_layers
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.map_layer import HydrantResponse
from app.services import fire_code_notify
from app.services.fire_code_notify import recipients
from app.services.staff_copy import fire_code

AREA = uuid4()
PRESSER = uuid4()
FV, BFP, MEDICAL, POLICE, HUB, CREW = (uuid4() for _ in range(6))
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


class _PeopleDb:
    """Coordinators by agency, the hub's people, and the incident's crews."""

    def __init__(self, agencies_asked: list[str]) -> None:
        self.agencies_asked = agencies_asked

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert "selected_agencies" in query
        return self.agencies_asked

    async def fetch(self, query: str, *args: Any) -> list[dict[str, UUID]]:
        if "is_central_hub" in query:
            return [{"id": HUB}]
        if "dispatch_logs" in query:
            return [{"responder_id": CREW}, {"responder_id": PRESSER}]
        by_agency = {"fire_volunteer": FV, "bfp": BFP, "medical": MEDICAL, "police": POLICE}
        return [{"id": by_agency[a]} for a in args[0] if a in by_agency] + [{"id": PRESSER}]


@pytest.mark.parametrize(
    ("code", "asked", "who"),
    [
        # Water: the fire service's coordinators.
        ("FC-6", ["police"], {FV, BFP}),
        # More units: every agency the fire is on (Fire Volunteer brings BFP).
        ("FC-7", ["fire_volunteer", "police"], {FV, BFP, POLICE}),
        # A casualty: medical coordinators and the central hub.
        ("FC-8", ["fire_volunteer"], {MEDICAL, HUB}),
        # Progress: the incident's crews and its agencies' coordinators.
        ("FC-1", ["bfp"], {FV, BFP, CREW}),
        ("FC-3", ["medical"], {MEDICAL, CREW}),
    ],
)
async def test_each_code_reaches_who_it_asks_never_the_presser(
    code: str, asked: list[str], who: set[UUID]
) -> None:
    db = _PeopleDb(asked)
    assert set(await recipients(db, AREA, code, PRESSER)) == who  # type: ignore[arg-type]


def test_the_alert_names_the_code_who_and_where() -> None:
    title, body = fire_code(
        "en", "FC-6", "Water Supply Needed", "Ana Cruz", "BFP Pasay",
        "Near F. Victor St., Brgy 76, Pasay",
    )
    assert title == "FC-6 · Water Supply Needed"
    assert body == (
        "Ana Cruz (BFP Pasay) pressed it for the fire near F. Victor St., Brgy 76, Pasay."
    )
    _, tl = fire_code("tl", "FC-8", "Possible Casualty", "Ana Cruz", None, "Near F. Victor St.")
    assert tl.startswith("Pinindot ni Ana Cruz para sa sunog malapit sa F. Victor St.")


def test_only_codes_that_ask_ring() -> None:
    assert fire_code_notify.ASKS == {"FC-6", "FC-7", "FC-8"}


# --------------------------------------------------------------------------- #
# Pressing
# --------------------------------------------------------------------------- #
class _PressDb:
    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.fire_codes" in query:
            return {
                "code_number": "FC-6", "name": "Water Supply Needed",
                "target_role": "response_team", "target_agency": None, "is_active": True,
            }
        if "insert into public.fire_code_events" in query:
            return {
                "id": uuid4(), "fire_code_id": args[0], "area_id": args[1],
                "pressed_by": args[2], "pressed_at": NOW, "notes": args[3],
            }
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return 1


@pytest.fixture
def press(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[str]]]:
    done: list[str] = []

    async def _finish(db: Any, area: UUID, event: str, **_: Any) -> None:
        done.append(event)

    async def _notify(db: Any, area: UUID, code: str, name: str, by: UUID) -> int:
        done.append(f"notified {code}")
        return 1

    async def _quiet(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(fire_codes, "finish_incident_change", _finish)
    monkeypatch.setattr(fire_codes, "notify_fire_code", _notify)
    monkeypatch.setattr(fire_codes.manager, "broadcast", _quiet)
    app.dependency_overrides[get_database] = lambda: _PressDb()
    with TestClient(app) as client:
        yield client, done
    app.dependency_overrides.clear()


def _admin(agency: str, *, hub: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name=f"{agency} Admin", primary_org_id=uuid4(),
        org_name=f"{agency} Org", org_agency_type=agency, org_is_active=True,
        org_is_central_hub=hub,
    )


@pytest.mark.parametrize(
    ("who", "allowed"),
    [
        (_admin("bfp"), True),
        (_admin("fire_volunteer"), True),
        (_admin("barangay", hub=True), True),
        (_admin("police"), False),
        (AuthenticatedUser(id=uuid4(), role="response_team", agency_type="bfp"), True),
        (AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="police"), False),
    ],
)
def test_who_presses_and_what_follows(
    press: tuple[TestClient, list[str]], who: AuthenticatedUser, allowed: bool
) -> None:
    client, done = press
    app.dependency_overrides[get_current_user] = lambda: who
    response = client.post(f"/fire-codes/{uuid4()}/press", json={"area_id": str(AREA)})
    if not allowed:
        assert response.status_code == 403
        assert done == []
        return
    assert response.status_code == 201, response.text
    assert response.json()["pressed_by_name"] == who.full_name
    # On the incident everywhere, and to whoever the code is for.
    assert done == ["fire_code_pressed", "notified FC-6"]


# --------------------------------------------------------------------------- #
# Hydrants
# --------------------------------------------------------------------------- #
def test_a_hydrant_is_verified_by_a_field_check_for_six_months() -> None:
    assert "interval '6 months'" in map_layers._HYDRANT_COLS
    assert "as verified" in map_layers._HYDRANT_COLS
    row = {
        "id": uuid4(), "latitude": 14.5, "longitude": 121.0, "bfp_status": "unknown",
        "effective_status": "unknown", "source": "osm", "is_active": True,
        "created_at": NOW, "updated_at": NOW,
    }
    assert HydrantResponse.model_validate(row).verified is False
    assert HydrantResponse.model_validate({**row, "verified": True}).verified is True
