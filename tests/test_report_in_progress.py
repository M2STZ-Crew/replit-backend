"""One report at a time (hermetic).

While a resident's last report is still a live incident, a second one is
refused before anything is uploaded or stored: it is almost always the same fire
sent again. These pin the refusal, what it tells the app, and that a resident
with nothing in progress still gets through.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import get_current_user, get_database, get_storage_client
from app.api.routes import reports
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services.incident import active_area_sql

_AREA = uuid4()
_EARLIER_REPORT = uuid4()


class _Db:
    """Answers the in-progress check with [pending], and the rest of a submit."""

    def __init__(self, pending: dict[str, Any] | None) -> None:
        self.pending = pending
        self.inserted = False
        self.queries: list[str] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.queries.append(query)
        if "from public.reports r" in query and "area_reports" in query:
            return self.pending
        if "insert into public.reports" in query:
            self.inserted = True
            return {"id": args[0], "created_at": datetime.now(UTC)}
        if "from public.areas" in query:
            return {"designation": "Area 3", "centroid_lat": 14.54, "centroid_lng": 121.0}
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "UPDATE"


class _Storage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []

    async def upload(self, *, bucket: str, path: str, **_: Any) -> None:
        self.uploaded.append(f"{bucket}/{path}")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, storage: _Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    user = AuthenticatedUser(id=uuid4(), role="general_user", verified_percent=60)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_storage_client] = lambda: storage

    async def _cluster(*_: Any, **__: Any) -> UUID:
        return _AREA

    async def _notify(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(reports, "cluster_report", _cluster)
    monkeypatch.setattr(reports, "notify_area_neighbors", _notify)


def _submit(client: TestClient) -> Any:
    buf = BytesIO()
    Image.new("RGB", (12, 8), "red").save(buf, format="PNG")
    return client.post(
        "/reports/submit",
        data={"device_lat": "14.54", "device_lng": "121.0", "selected_agencies": "fire_volunteer"},
        files={"photo": ("fire.png", buf.getvalue(), "image/png")},
    )


def test_a_second_report_is_refused_while_the_first_is_live(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _Db({"report_id": _EARLIER_REPORT, "area_id": _AREA, "designation": "Area 3"})
    storage = _Storage()
    _wire(db, storage, monkeypatch)

    response = _submit(client)

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "report_in_progress"
    assert "already have a report in progress" in body["message"]
    # The app follows the report it is pointed at, rather than guessing.
    assert body["details"] == {
        "report_id": str(_EARLIER_REPORT),
        "area_id": str(_AREA),
        "area_designation": "Area 3",
    }
    assert storage.uploaded == [], "refused before the photo was stored"
    assert not db.inserted


def test_with_nothing_in_progress_the_report_goes_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _Db(None)
    storage = _Storage()
    _wire(db, storage, monkeypatch)

    response = _submit(client)

    assert response.status_code == 201, response.text
    assert response.json()["area_id"] == str(_AREA)
    assert db.inserted
    assert len(storage.uploaded) == 1


def test_only_a_live_incident_from_the_last_twelve_hours_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _Db(None)
    _wire(db, _Storage(), monkeypatch)

    _submit(client)

    check = db.queries[0]
    # Fire out, closed, rejected and merged areas hold nobody back ...
    assert active_area_sql("a") in check
    # ... and neither does one nobody picked up in twelve hours.
    assert "make_interval(hours => $2)" in check
    assert reports.IN_PROGRESS_HOURS == 12
