"""v1.12.35: an account asked to be deleted is frozen for 30 days first.

16 Nov 2026: "make the account is in freeze for 30 days before actual deleting
it? (they can still recover it within 30 days)", and the privacy policy and
account pages on a residents' site of their own (reportwhatslit-app).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import (
    get_access_token,
    get_auth_client,
    get_current_user,
    get_database,
    get_verified_user,
)
from app.api.routes import admin
from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, ForbiddenError
from app.integrations.supabase_auth import AuthError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import account_deletion

PASSWORD = "right-password-1"
REQUESTED = datetime(2026, 11, 16, 3, 0, tzinfo=UTC)


class _Auth:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        self.calls: list[tuple[str, Any]] = []
        self.sessions = 0

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        self.calls.append(("sign_in", email))
        if password != PASSWORD:
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        self.sessions += 1
        return {
            "access_token": f"check-{self.sessions}",
            "refresh_token": "r",
            "user": {"id": str(self.user_id), "email": email},
        }

    async def sign_out(self, *, access_token: str, scope: str | None = None) -> None:
        self.calls.append(("sign_out", (access_token, scope)))

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.calls.append(("delete", user_id))


class _Db:
    def __init__(self, *, role: str = "general_user", requested: datetime | None = None) -> None:
        self.role = role
        self.requested = requested
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "set deletion_requested_at = coalesce" in query:
            self.requested = self.requested or REQUESTED
            return self.requested
        if "set deletion_requested_at = null" in query:
            if self.requested is None:
                return None
            self.requested = None
            return args[0]
        if "select role::text" in query:
            return self.role
        if "->> 'deletion_requested_at'" in query:
            return self.requested
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    def audit(self) -> list[tuple[Any, ...]]:
        return [args for q, args in self.executed if "insert into public.audit_logs" in q]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, *, role: str = "general_user") -> _Auth:
    user = AuthenticatedUser(id=uuid4(), role=role, email="m@x.ph")
    auth = _Auth(user.id)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_user] = lambda: user
    app.dependency_overrides[get_access_token] = lambda: "this-session"
    app.dependency_overrides[get_auth_client] = lambda: auth
    app.dependency_overrides[get_database] = lambda: db
    return auth


# --------------------------------------------------------------------------- #
# Asking, from the app
# --------------------------------------------------------------------------- #
def test_the_app_freezes_the_account_and_signs_it_out_everywhere(client: TestClient) -> None:
    db = _Db()
    auth = _wire(db)
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert datetime.fromisoformat(body["delete_after"]) == REQUESTED + timedelta(days=30)
    assert "16 December 2026" in body["message"]
    assert auth.calls[0] == ("sign_in", "m@x.ph")
    assert ("sign_out", ("this-session", "global")) in auth.calls
    assert not any(c == "delete" for c, _ in auth.calls), "nothing is deleted yet"
    assert any("device_tokens set is_active = false" in q for q, _ in db.executed)
    assert len(db.audit()) == 1 and "account.delete_requested" in db.audit()[0]


def test_a_wrong_password_freezes_nothing(client: TestClient) -> None:
    db = _Db()
    auth = _wire(db)
    response = client.post("/auth/me/delete", json={"password": "guess"})
    assert response.status_code == 400
    assert response.json()["error"] == "wrong_password"
    assert db.requested is None
    assert [c for c, _ in auth.calls] == ["sign_in"]


@pytest.mark.parametrize("role", ["sub_admin", "response_team", "admin"])
def test_a_staff_account_is_its_organizations(client: TestClient, role: str) -> None:
    db = _Db(role=role)
    auth = _wire(db, role=role)
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"] == "staff_account"
    assert auth.calls == [] and db.requested is None


# --------------------------------------------------------------------------- #
# Asking, and restoring, from the residents' site
# --------------------------------------------------------------------------- #
def test_the_site_freezes_with_the_email_and_password(client: TestClient) -> None:
    db = _Db()
    auth = _wire(db)
    response = client.post("/auth/delete", json={"email": "m@x.ph", "password": PASSWORD})
    assert response.status_code == 200
    assert db.requested == REQUESTED
    assert ("sign_out", ("check-1", "global")) in auth.calls
    assert "account.delete_requested" in db.audit()[0]


def test_the_site_refuses_a_staff_account_and_leaves_no_session(client: TestClient) -> None:
    db = _Db(role="sub_admin")
    auth = _wire(db)
    response = client.post("/auth/delete", json={"email": "m@x.ph", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"] == "staff_account"
    assert db.requested is None
    assert ("sign_out", ("check-1", "local")) in auth.calls


def test_the_site_says_a_wrong_email_or_password_plainly(client: TestClient) -> None:
    db = _Db()
    _wire(db)
    response = client.post("/auth/delete", json={"email": "m@x.ph", "password": "guess"})
    assert response.status_code == 400
    assert response.json()["error"] == "wrong_password"


def test_restoring_within_the_30_days_unfreezes_it(client: TestClient) -> None:
    db = _Db(requested=REQUESTED)
    auth = _wire(db)
    response = client.post("/auth/restore", json={"email": "m@x.ph", "password": PASSWORD})
    assert response.status_code == 200
    assert "restored" in response.json()["message"]
    assert db.requested is None
    assert ("sign_out", ("check-1", "local")) in auth.calls
    assert "account.restore" in db.audit()[0]


def test_restoring_an_account_that_is_not_frozen_says_so(client: TestClient) -> None:
    db = _Db()
    _wire(db)
    response = client.post("/auth/restore", json={"email": "m@x.ph", "password": PASSWORD})
    assert response.status_code == 409
    assert response.json()["error"] == "not_scheduled"


# --------------------------------------------------------------------------- #
# A frozen account
# --------------------------------------------------------------------------- #
def test_a_frozen_account_signs_in_to_no_session_and_hears_the_date(client: TestClient) -> None:
    db = _Db(requested=REQUESTED)
    auth = _wire(db)
    response = client.post("/auth/login", json={"email": "m@x.ph", "password": PASSWORD})
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "account_pending_deletion"
    assert datetime.fromisoformat(body["details"]["delete_after"]) == REQUESTED + timedelta(days=30)
    assert "Restore my account" in body["message"]
    assert ("sign_out", ("check-1", "local")) in auth.calls


async def test_every_request_of_a_frozen_account_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()

    async def claims(token: str, client: Any) -> dict[str, Any]:
        return {"sub": str(user_id), "session_id": "s"}

    async def newest(*args: Any) -> None:
        return None

    class _Profile:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            assert "deletion_requested_at" in query
            return {
                "id": user_id,
                "role": "general_user",
                "is_active": True,
                "org_standing": "active",
                "deletion_requested_at": REQUESTED,
            }

    monkeypatch.setattr(deps, "decode_access_token", claims)
    monkeypatch.setattr(deps, "assert_newest_session", newest)
    with pytest.raises(ForbiddenError) as caught:
        await get_current_user(
            request=SimpleNamespace(state=SimpleNamespace()),  # type: ignore[arg-type]
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="t"),
            db=_Profile(),  # type: ignore[arg-type]
            http_client=None,  # type: ignore[arg-type]
        )
    assert caught.value.error_code == "account_pending_deletion"


# --------------------------------------------------------------------------- #
# After 30 days
# --------------------------------------------------------------------------- #
class _Storage:
    def __init__(self, failing: set[UUID]) -> None:
        self.failing = failing
        self.removed: list[str] = []

    async def remove(self, *, bucket: str, path: str) -> None:
        if any(str(u) in path for u in self.failing):
            raise OSError("storage down")
        self.removed.append(path)


class _DueDb(_Db):
    def __init__(self, due: list[UUID]) -> None:
        super().__init__()
        self.due = due
        self.asked: tuple[Any, ...] = ()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        assert "make_interval(days => $1::int)" in query
        self.asked = args
        return [{"id": u} for u in self.due]


async def test_the_job_deletes_only_accounts_frozen_for_30_days() -> None:
    gone, stuck = uuid4(), uuid4()
    db = _DueDb([gone, stuck])
    auth = _Auth(gone)
    deleted = await account_deletion.purge_due(db, auth, _Storage({stuck}))
    assert deleted == 1
    assert db.asked[0] == 30
    assert auth.calls == [("delete", str(gone))], "a frozen account whose photos stay, stays"
    assert len(db.audit()) == 1 and "account.deleted" in db.audit()[0]


def test_the_day_it_goes_is_said_in_philippine_time() -> None:
    assert account_deletion.day_of(datetime(2026, 12, 15, 17, 0, tzinfo=UTC)) == "16 December 2026"


# --------------------------------------------------------------------------- #
# Around it
# --------------------------------------------------------------------------- #
def test_the_residents_site_may_call_the_server() -> None:
    assert "https://reportwhatslit-app.vercel.app" in get_settings().cors_origins_list
    assert "https://reportwhatslit.vercel.app" in get_settings().cors_origins_list


def test_a_frozen_accounts_national_id_leaves_the_review_queue() -> None:
    source = inspect.getsource(admin.list_pending_verifications)
    assert "deletion_requested_at') is null" in source


async def test_without_the_column_yet_deleting_says_so_plainly() -> None:
    class _OldDb(_Db):
        async def fetchval(self, query: str, *args: Any) -> Any:
            raise RuntimeError('column "deletion_requested_at" does not exist')

    with pytest.raises(ExternalServiceError) as caught:
        await account_deletion.schedule(_OldDb(), uuid4())
    assert caught.value.status_code == 503
    assert caught.value.error_code == "deletion_unavailable"


def test_reads_survive_a_database_without_the_column() -> None:
    # Sign-in and every request read it through to_jsonb, which is null when
    # the column is not there yet, so merging before the migration breaks nothing.
    assert "to_jsonb(u) ->> 'deletion_requested_at'" in deps.CURRENT_USER_SQL
