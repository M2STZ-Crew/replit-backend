"""Suspend, revoke, restore, delete an affiliate (v1.12.28; hermetic).

12 November 2026: "affiliate management (freeze account, or soft delete, or
hard delete, for revoked reasons)". All three, each with a reason, audited:
suspend freezes and restores any time; revoke freezes, keeps the record and
restores for 30 days; delete permanently only with no incidents on record.
The central hub and the reviewer's own organisation are not touched.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_auth_client, get_database
from app.api.routes import affiliate_standing
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import OrganizationSummary

_NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
_HUB = uuid4()


class _Org:
    def __init__(self, name: str = "Pasay Fire Volunteers", *, hub: bool = False) -> None:
        self.id = uuid4()
        self.name = name
        self.standing = "active"
        self.changed_at: datetime | None = None
        self.hub = hub
        self.is_active = True
        self.deleted = False
        self.members = [uuid4(), uuid4()]
        self.incidents = 0


class _Db:
    def __init__(self, org: _Org) -> None:
        self.org = org

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if args[0] != self.org.id or self.org.deleted:
            return None
        return {
            "id": self.org.id,
            "name": self.org.name,
            "standing": self.org.standing,
            "standing_changed_at": self.org.changed_at,
            "is_central_hub": self.org.hub,
        }

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "select now()" in query:
            return _NOW
        if "area_acceptances" in query:
            return self.org.incidents
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return [{"id": m} for m in self.org.members]

    async def execute(self, query: str, *args: Any) -> str:
        if "update public.organizations" in query:
            self.org.standing = args[1]
            self.org.is_active = args[1] == "active"
            self.org.changed_at = _NOW
        if "delete from public.organizations" in query:
            self.org.deleted = True
        return "OK"


class _Auth:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)


def _reviewer(org: UUID = _HUB) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="admin", primary_org_id=org, full_name="Hub")


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def _audit(*_a: Any, **kw: Any) -> None:
        seen.append(kw)

    async def _summary(db: Any, org_id: UUID) -> OrganizationSummary:
        org: _Org = db.org
        return OrganizationSummary(
            id=org.id, name=org.name, agency_type="fire_volunteer",
            is_active=org.is_active, created_at=_NOW, standing=org.standing,
        )

    monkeypatch.setattr(affiliate_standing, "record_audit", _audit)
    monkeypatch.setattr(affiliate_standing, "_summary", _summary)
    return seen


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(user: AuthenticatedUser, db: _Db, auth: _Auth | None = None) -> None:
    reviewer = affiliate_standing.AffiliateReviewer.__metadata__[0].dependency
    app.dependency_overrides[reviewer] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_auth_client] = lambda: auth or _Auth()


def _post(client: TestClient, org: _Org, act: str, **body: Any) -> Any:
    return client.post(f"/affiliates/organizations/{org.id}/{act}", json=body)


# ------------------------------------------------------------- suspend ---
def test_suspend_freezes_with_a_reason_and_is_audited(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    _as(_reviewer(), _Db(org))

    r = _post(client, org, "suspend", reason="misconduct", note="Reports of fake alarms")

    assert r.status_code == 200, r.text
    assert r.json()["standing"] == "suspended"
    assert org.standing == "suspended" and org.is_active is False
    assert audits[0]["action"] == "affiliate.suspend"
    assert audits[0]["metadata"]["reason"] == "misconduct"


def test_other_needs_a_note(client: TestClient, audits: list[dict[str, Any]]) -> None:
    org = _Org()
    _as(_reviewer(), _Db(org))
    r = _post(client, org, "suspend", reason="other")
    assert r.status_code == 400
    assert r.json()["error"] == "note_required"
    assert org.standing == "active"


def test_an_unknown_reason_is_refused(client: TestClient, audits: list[dict[str, Any]]) -> None:
    org = _Org()
    _as(_reviewer(), _Db(org))
    assert _post(client, org, "suspend", reason="bored").status_code == 422


@pytest.mark.parametrize("case", ["hub", "own"])
def test_the_hub_and_your_own_organization_are_not_touched(
    client: TestClient, audits: list[dict[str, Any]], case: str
) -> None:
    org = _Org(hub=case == "hub")
    _as(_reviewer(org.id if case == "own" else _HUB), _Db(org))
    r = _post(client, org, "suspend", reason="inactive")
    assert r.status_code == 409
    assert r.json()["error"] == ("central_hub" if case == "hub" else "own_organization")
    assert org.standing == "active"


# -------------------------------------------------------------- revoke ---
def test_revoke_then_restore_within_thirty_days(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    _as(_reviewer(), _Db(org))
    assert _post(client, org, "revoke", reason="duplicate").json()["standing"] == "revoked"

    r = _post(client, org, "restore", note="It was the other one")

    assert r.status_code == 200, r.text
    assert org.standing == "active" and org.is_active is True
    assert [a["action"] for a in audits] == ["affiliate.revoke", "affiliate.restore"]


def test_after_thirty_days_a_revoked_organization_stays_revoked(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    org.standing = "revoked"
    org.changed_at = _NOW - timedelta(days=31)
    _as(_reviewer(), _Db(org))

    r = _post(client, org, "restore")

    assert r.status_code == 409
    assert r.json()["error"] == "restore_window_passed"
    assert org.standing == "revoked"


def test_a_revoked_organization_is_restored_before_it_is_suspended(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    org.standing = "revoked"
    org.changed_at = _NOW
    _as(_reviewer(), _Db(org))
    r = _post(client, org, "suspend", reason="inactive")
    assert r.status_code == 409 and r.json()["error"] == "restore_first"


# -------------------------------------------------------------- delete ---
def test_delete_needs_the_name_typed(client: TestClient, audits: list[dict[str, Any]]) -> None:
    org = _Org()
    auth = _Auth()
    _as(_reviewer(), _Db(org), auth)
    r = _post(client, org, "delete", reason="fraudulent_application", confirm_name="Pasay")
    assert r.status_code == 400 and r.json()["error"] == "name_mismatch"
    assert auth.deleted == [] and not org.deleted


def test_an_organization_with_incidents_on_record_is_revoked_not_deleted(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    org.incidents = 3
    auth = _Auth()
    _as(_reviewer(), _Db(org), auth)
    r = _post(
        client, org, "delete", reason="organization_request",
        confirm_name="pasay fire volunteers",
    )
    assert r.status_code == 409
    assert r.json()["error"] == "has_incidents"
    assert auth.deleted == [] and not org.deleted


def test_delete_removes_every_account_and_the_organization(
    client: TestClient, audits: list[dict[str, Any]]
) -> None:
    org = _Org()
    auth = _Auth()
    _as(_reviewer(), _Db(org), auth)

    r = _post(
        client, org, "delete", reason="fraudulent_application",
        confirm_name="Pasay Fire Volunteers",
    )

    assert r.status_code == 200, r.text
    assert r.json()["accounts_deleted"] == 2
    assert auth.deleted == [str(m) for m in org.members]
    assert org.deleted
    assert audits[-1]["action"] == "affiliate.delete"


# --------------------------------------------------------- frozen sign-in ---
def test_nobody_of_a_frozen_organization_signs_in_or_acts() -> None:
    source = inspect.getsource(deps.get_current_user)
    assert "ORGANIZATION_FROZEN" in source
    assert 'error_code=f"organization_{standing}"' in source
    assert set(deps.ORGANIZATION_FROZEN) == {"suspended", "revoked"}
    assert "coalesce(to_jsonb(o) ->> 'standing', 'active') as org_standing" in (
        deps.CURRENT_USER_SQL
    )


def test_the_migration_holds_the_reasons() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "supabase/migrations/20261112120000_affiliate_standing.sql"
    ).read_text(encoding="utf-8")
    for reason in affiliate_standing.REASON_LABELS:
        assert f"'{reason}'" in sql
    assert "check (standing in ('active', 'suspended', 'revoked'))" in sql
