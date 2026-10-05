"""The coordinators' AI summaries list and the browser PDF link (hermetic, v1.12.5).

What these pin:
- every incident a team filed a report for is listed, with its newest summary;
  one with no summary, or one older than its newest report, is "writing" and
  its summary is started — once, not on every load — or "unavailable" when the
  server has no AI key;
- only coordinators (and admin) read the list, and they see what their agency
  sees;
- a download link works for five minutes, for one incident, for someone who
  can still see it, and needs no sign-in header — a browser has none.

Nothing here calls DeepSeek or builds a real summary.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database
from app.api.routes import ai as ai_routes
from app.api.routes import incident_reports
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import ai_summary, report_links
from app.services.ai_summary import (
    BACKFILL_PER_LOAD,
    SUMMARY_RETRY_AFTER,
    claim_summary,
    summary_state,
)
from app.services.report_links import (
    ExpiredReportLinkError,
    InvalidReportLinkError,
    sign_report_link,
    verify_report_link,
)

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A known signing secret, and no summaries remembered from another test."""
    monkeypatch.setattr(
        report_links,
        "get_settings",
        lambda: SimpleNamespace(supabase_jwt_secret="test-secret", supabase_service_role_key=""),
    )
    ai_summary._started.clear()
    yield
    ai_summary._started.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _user(role: str = "sub_admin", agency: str | None = "fire_volunteer") -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, agency_type=agency, phone_verified=True)


# --------------------------------------------------------------------------- #
# The download link
# --------------------------------------------------------------------------- #
def test_a_link_opens_its_own_incident_for_its_own_user() -> None:
    area, user = uuid4(), uuid4()
    token, expires_at = sign_report_link(area, user, now=NOW)
    assert expires_at == NOW + timedelta(minutes=5)
    assert verify_report_link(area, token, now=NOW + timedelta(minutes=4)) == user


def test_a_link_expires_after_five_minutes() -> None:
    area = uuid4()
    token, _ = sign_report_link(area, uuid4(), now=NOW)
    with pytest.raises(ExpiredReportLinkError):
        verify_report_link(area, token, now=NOW + timedelta(minutes=5, seconds=1))


def test_a_link_does_not_open_another_incident() -> None:
    token, _ = sign_report_link(uuid4(), uuid4(), now=NOW)
    with pytest.raises(InvalidReportLinkError):
        verify_report_link(uuid4(), token, now=NOW)


@pytest.mark.parametrize("change", ["user", "expiry", "signature"])
def test_a_changed_link_is_refused(change: str) -> None:
    area = uuid4()
    token, _ = sign_report_link(area, uuid4(), now=NOW)
    user_hex, expires, signature = token.split(".")
    if change == "user":
        user_hex = uuid4().hex
    elif change == "expiry":
        expires = str(int(expires) + 3600)
    else:
        signature = signature[:-2] + ("AA" if signature[-2:] != "AA" else "BB")
    with pytest.raises(InvalidReportLinkError):
        verify_report_link(area, f"{user_hex}.{expires}.{signature}", now=NOW)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "nothex.123.sig", "a.b.c.d"])
def test_a_malformed_link_is_refused(token: str) -> None:
    with pytest.raises(InvalidReportLinkError):
        verify_report_link(uuid4(), token, now=NOW)


def test_the_link_is_url_safe() -> None:
    token, _ = sign_report_link(uuid4(), uuid4(), now=NOW)
    assert all(c.isalnum() or c in "._-" for c in token)


def test_the_jwt_secret_is_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        report_links,
        "get_settings",
        lambda: SimpleNamespace(supabase_jwt_secret="", supabase_service_role_key="srk"),
    )
    area, user = uuid4(), uuid4()
    token, _ = sign_report_link(area, user, now=NOW)
    assert verify_report_link(area, token, now=NOW) == user


# --------------------------------------------------------------------------- #
# Which summaries are owed
# --------------------------------------------------------------------------- #
def test_a_summary_written_after_the_last_report_is_ready() -> None:
    row = {"generated_at": NOW, "last_filed_at": NOW - timedelta(seconds=30)}
    assert summary_state(row, configured=True) == "ready"
    assert summary_state(row, configured=False) == "ready"


def test_no_summary_is_owed() -> None:
    row = {"generated_at": None, "last_filed_at": NOW}
    assert summary_state(row, configured=True) == "writing"
    assert summary_state(row, configured=False) == "unavailable"


def test_a_team_that_filed_after_the_summary_makes_it_owed() -> None:
    row = {"generated_at": NOW, "last_filed_at": NOW + timedelta(minutes=3)}
    assert summary_state(row, configured=True) == "writing"


def test_a_summary_is_started_once_in_ten_minutes() -> None:
    area = uuid4()
    assert claim_summary(area, now=1000.0) is True
    assert claim_summary(area, now=1000.0 + SUMMARY_RETRY_AFTER - 1) is False
    assert claim_summary(area, now=1000.0 + SUMMARY_RETRY_AFTER) is True


# --------------------------------------------------------------------------- #
# GET /ai-summaries
# --------------------------------------------------------------------------- #
def _row(**cols: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "area_id": uuid4(),
        "designation": "Area 3",
        "status": "closed",
        "reported_at": NOW - timedelta(hours=2),
        "closed_at": NOW - timedelta(hours=1),
        "reports_filed": 1,
        "teams": ["Hercules Fire Brigade"],
        "last_filed_at": NOW - timedelta(hours=1),
        "summary_id": uuid4(),
        "summary_text": "A kitchen fire on Leveriza St.",
        "model": "deepseek-flash",
        "generated_at": NOW - timedelta(minutes=59),
    }
    base.update(cols)
    return base


def _missing(**cols: Any) -> dict[str, Any]:
    return _row(summary_id=None, summary_text=None, model=None, generated_at=None, **cols)


class _ListDb:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((query, args))
        return self.rows[: args[0]]


def _wire_list(
    monkeypatch: pytest.MonkeyPatch,
    user: AuthenticatedUser,
    rows: list[dict[str, Any]],
    *,
    configured: bool = True,
) -> tuple[_ListDb, list[UUID]]:
    db = _ListDb(rows)
    started: list[UUID] = []

    async def fake_summarize(area_id: UUID) -> None:
        started.append(area_id)

    monkeypatch.setattr(ai_routes, "summarize_in_background", fake_summarize)
    monkeypatch.setattr(
        ai_routes, "get_settings", lambda: SimpleNamespace(deepseek_configured=configured)
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    return db, started


def test_a_coordinator_sees_each_summarized_incident(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _row(teams=["Hercules Fire Brigade", "BFP Pasay"], reports_filed=2)
    _, started = _wire_list(monkeypatch, _user(), [ready])
    resp = client.get("/ai-summaries")
    assert resp.status_code == 200, resp.text
    [item] = resp.json()
    assert item["state"] == "ready"
    assert item["summary_text"] == "A kitchen fire on Leveriza St."
    assert item["teams"] == ["Hercules Fire Brigade", "BFP Pasay"]
    assert item["reports_filed"] == 2
    assert started == [], "nothing owed, nothing written"


def test_a_missing_summary_is_written_without_anyone_asking(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = _missing()
    _, started = _wire_list(monkeypatch, _user(), [missing])
    [item] = client.get("/ai-summaries").json()
    assert item["state"] == "writing" and item["summary_text"] is None
    assert started == [missing["area_id"]]
    # Refreshing does not start a second one.
    client.get("/ai-summaries")
    assert started == [missing["area_id"]]


def test_an_outdated_summary_is_shown_while_it_is_rewritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    outdated = _row(last_filed_at=NOW, generated_at=NOW - timedelta(hours=1))
    _, started = _wire_list(monkeypatch, _user(), [outdated])
    [item] = client.get("/ai-summaries").json()
    assert item["state"] == "writing"
    assert item["summary_text"] == "A kitchen fire on Leveriza St."
    assert started == [outdated["area_id"]]


def test_without_an_ai_key_nothing_is_started(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, started = _wire_list(monkeypatch, _user(), [_missing()], configured=False)
    [item] = client.get("/ai-summaries").json()
    assert item["state"] == "unavailable"
    assert started == []


def test_a_backlog_is_worked_through_a_few_at_a_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [_missing() for _ in range(BACKFILL_PER_LOAD + 3)]
    _, started = _wire_list(monkeypatch, _user(), rows)
    client.get("/ai-summaries")
    assert len(started) == BACKFILL_PER_LOAD
    client.get("/ai-summaries")
    assert len(started) == BACKFILL_PER_LOAD + 3
    assert len(set(started)) == len(started)


def test_a_fire_coordinator_sees_both_fire_agencies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _ = _wire_list(monkeypatch, _user("sub_admin", "bfp"), [])
    client.get("/ai-summaries", params={"limit": 20})
    query, args = db.calls[0]
    assert args[0] == 20
    assert sorted(args[1]) == ["bfp", "fire_volunteer"]
    assert "selected_agencies &&" in query


def test_admin_sees_every_incident(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = _wire_list(monkeypatch, _user("admin", None), [])
    assert client.get("/ai-summaries").status_code == 200
    query, args = db.calls[0]
    assert len(args) == 1 and "selected_agencies" not in query


@pytest.mark.parametrize(
    ("role", "agency"),
    [("sub_admin", "police"), ("response_team", "fire_volunteer"), ("general_user", None)],
)
def test_only_coordinators_read_the_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, role: str, agency: str | None
) -> None:
    db, started = _wire_list(monkeypatch, _user(role, agency), [_missing()])
    assert client.get("/ai-summaries").status_code == 403
    assert db.calls == [] and started == []


def test_the_list_needs_a_sign_in(client: TestClient) -> None:
    assert client.get("/ai-summaries").status_code == 401


# --------------------------------------------------------------------------- #
# POST /incidents/{id}/report-link and GET .../report-download
# --------------------------------------------------------------------------- #
class _PdfDb:
    """An incident, whether the caller's agency can see it, and the users."""

    def __init__(self, area_id: UUID, *, visible: bool = True) -> None:
        self.area_id = area_id
        self.visible = visible
        self.users: dict[UUID, dict[str, Any]] = {}

    def add(self, user: AuthenticatedUser, *, is_active: bool = True) -> None:
        self.users[user.id] = {
            "id": user.id,
            "role": user.role,
            "agency_type": user.agency_type,
            "is_active": is_active,
        }

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "select 1 from public.areas" in query:
            return 1 if args[0] == self.area_id else None
        assert "selected_agencies" in query
        return self.visible

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        assert "from public.users" in query
        return self.users.get(args[0])


@pytest.fixture
def pdf(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Stand in for the PDF builder; records which incident was built."""
    built: list[UUID] = []

    async def fake_build(db: Any, incident_id: UUID) -> tuple[bytes, str]:
        built.append(incident_id)
        return b"%PDF-1.4 test", "Fire-report-Area-3-2026-10-05.pdf"

    monkeypatch.setattr(incident_reports, "_build_pdf", fake_build)
    return built


def _link(client: TestClient, db: _PdfDb, user: AuthenticatedUser) -> str:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    resp = client.post(f"/incidents/{db.area_id}/report-link")
    assert resp.status_code == 200, resp.text
    path = resp.json()["path"]
    assert path.startswith(f"/incidents/{db.area_id}/report-download?token=")
    # The browser has no sign-in.
    del app.dependency_overrides[get_current_user]
    return path


def test_the_browser_downloads_the_pdf_with_the_link(
    client: TestClient, pdf: list[UUID]
) -> None:
    db = _PdfDb(uuid4())
    coordinator = _user()
    db.add(coordinator)
    resp = client.get(_link(client, db, coordinator))
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF-")
    assert resp.headers["content-type"] == "application/pdf"
    assert 'filename="Fire-report-Area-3-2026-10-05.pdf"' in resp.headers["content-disposition"]
    assert "no-store" in resp.headers["cache-control"]
    assert pdf == [db.area_id]


def test_no_link_for_an_incident_another_agency_owns(client: TestClient) -> None:
    db = _PdfDb(uuid4(), visible=False)
    app.dependency_overrides[get_current_user] = lambda: _user("sub_admin", "police")
    app.dependency_overrides[get_database] = lambda: db
    assert client.post(f"/incidents/{db.area_id}/report-link").status_code == 403


def test_a_deactivated_account_link_stops_working(
    client: TestClient, pdf: list[UUID]
) -> None:
    db = _PdfDb(uuid4())
    responder = _user("response_team")
    db.add(responder)
    path = _link(client, db, responder)
    db.users[responder.id]["is_active"] = False
    resp = client.get(path)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("text/plain")
    assert pdf == []


def test_a_link_for_one_incident_does_not_open_another(
    client: TestClient, pdf: list[UUID]
) -> None:
    db = _PdfDb(uuid4())
    coordinator = _user()
    db.add(coordinator)
    token = _link(client, db, coordinator).split("token=")[1]
    other = uuid4()
    db.area_id = other
    resp = client.get(f"/incidents/{other}/report-download", params={"token": token})
    assert resp.status_code == 403 and pdf == []


def test_an_expired_link_says_so_in_words(client: TestClient, pdf: list[UUID]) -> None:
    db = _PdfDb(uuid4())
    coordinator = _user()
    db.add(coordinator)
    app.dependency_overrides[get_database] = lambda: db
    made = datetime.now(UTC) - timedelta(minutes=6)
    token, _ = sign_report_link(db.area_id, coordinator.id, now=made)
    resp = client.get(f"/incidents/{db.area_id}/report-download", params={"token": token})
    assert resp.status_code == 410
    assert "expired" in resp.text and "Download PDF again" in resp.text
    assert pdf == []


def test_the_file_is_named_for_the_incident_and_its_day() -> None:
    name = incident_reports._file_name(
        {"designation": "Area 3", "timestamps": {"reported_at": "2026-10-04T17:30:00+00:00"}}
    )
    # 5:30 PM UTC on the 4th is 1:30 AM on the 5th in the Philippines.
    assert name == "Fire-report-Area-3-2026-10-05.pdf"
    assert incident_reports._file_name({"designation": "", "timestamps": {}}) == (
        "Fire-report-incident.pdf"
    )
