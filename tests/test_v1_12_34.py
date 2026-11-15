"""v1.12.34: what the QA run on 15–16 Nov 2026 found, and Google Play's rules.

- A name is letters, with spaces, periods, apostrophes and hyphens (Z-10).
- An email whose domain takes no mail is refused at sign-up (D-02).
- A resident can delete their account, password first (Play: account deletion).
- A copy of the app from Google Play is not told of GitHub releases.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from email_validator import EmailSyntaxError, EmailUndeliverableError
from fastapi.testclient import TestClient

from app.api.deps import (
    get_auth_client,
    get_current_user,
    get_database,
    get_storage_client,
    get_verified_user,
)
from app.core.exceptions import BadRequestError
from app.integrations.fcm import app_version_of
from app.integrations.supabase_auth import AuthError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import email_deliverability as ed
from app.services.names import clean_name, ensure_valid_name, is_valid_name
from app.workers.app_updates import _DUE_SQL, is_older

PASSWORD = "right-password-1"


# --------------------------------------------------------------------------- #
# Names (Z-10)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "Juan Dela Cruz",
        "Ma. Luisa Santos",
        "Juan Dela Cruz Jr.",
        "O'Neil",
        "D’Angelo",
        "Anne-Marie",
        "Niño Peña",
        "ÑANDÚ",
        "José",
    ],
)
def test_names_people_have_pass(name: str) -> None:
    assert is_valid_name(name)
    assert ensure_valid_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["Juan 😀", "😀", "Juan123", "Juan_Cruz", "Juan, Cruz", "-Juan", "Juan@", "J/C", "'"],
)
def test_digits_emoji_and_symbols_are_refused(name: str) -> None:
    assert not is_valid_name(name)
    with pytest.raises(BadRequestError) as caught:
        ensure_valid_name(name)
    assert caught.value.error_code == "invalid_name"
    assert caught.value.details == {"field": "full_name"}


def test_a_name_is_kept_tidy_and_an_empty_one_is_none() -> None:
    assert clean_name("  Juan   Dela  Cruz ") == "Juan Dela Cruz"
    # A decomposed accent (e + combining acute) is stored composed, and passes.
    assert ensure_valid_name("José") == "José"
    assert ensure_valid_name("   ") is None
    assert ensure_valid_name(None) is None
    assert not is_valid_name("A" * 201)


# --------------------------------------------------------------------------- #
# Email deliverability (D-02)
# --------------------------------------------------------------------------- #
@pytest.fixture
def check_on(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []
    monkeypatch.setattr(ed.get_settings(), "email_deliverability_check", True)
    return asked


async def test_a_domain_that_takes_no_mail_is_refused(
    check_on: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def undeliverable(email: str) -> None:
        check_on.append(email)
        raise EmailUndeliverableError("The domain name qwerty-asdf.xyz does not exist.")

    monkeypatch.setattr(ed, "_check", undeliverable)
    with pytest.raises(BadRequestError) as caught:
        await ed.ensure_deliverable("juan@qwerty-asdf.xyz")
    assert caught.value.error_code == "undeliverable_email"
    assert caught.value.details == {"field": "email"}
    assert check_on == ["juan@qwerty-asdf.xyz"]


@pytest.mark.parametrize(
    "failure", [TimeoutError("slow"), OSError("no network"), EmailSyntaxError("x")]
)
async def test_a_lookup_that_fails_lets_the_address_through(
    check_on: list[str], monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def broken(email: str) -> None:
        raise failure

    monkeypatch.setattr(ed, "_check", broken)
    await ed.ensure_deliverable("juan@gmail.com")


async def test_a_domain_that_takes_mail_passes(
    check_on: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ed, "_check", check_on.append)
    await ed.ensure_deliverable("juan@gmail.com")
    assert check_on == ["juan@gmail.com"]


async def test_the_check_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed.get_settings(), "email_deliverability_check", False)

    def never(email: str) -> None:
        raise AssertionError("looked up while off")

    monkeypatch.setattr(ed, "_check", never)
    await ed.ensure_deliverable("juan@qwerty-asdf.xyz")


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
class _Auth:
    def __init__(self, *, delete_fails: bool = False) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.delete_fails = delete_fails

    async def sign_in_with_password(self, *, email: str, password: str) -> dict[str, Any]:
        self.calls.append(("sign_in", email))
        if password != PASSWORD:
            raise AuthError("Invalid login credentials", details={"gotrue_status": 400})
        return {"access_token": "check", "refresh_token": "r"}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.calls.append(("delete", user_id))
        if self.delete_fails:
            raise AuthError("Database error deleting user")

    async def sign_up(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("sign_up", kwargs))
        return {"access_token": "a", "refresh_token": "r", "user": {"id": str(uuid4())}}


class _Storage:
    def __init__(self, *, fails: bool = False) -> None:
        self.removed: list[str] = []
        self.fails = fails

    async def remove(self, *, bucket: str, path: str) -> None:
        if self.fails:
            raise OSError("storage down")
        self.removed.append(f"{bucket}/{path}")


class _Db:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.executed.append((query, args))
        return {
            "id": args[0],
            "email": "m@x.ph",
            "phone": None,
            "role": "general_user",
            "agency_type": None,
            "verified_percent": 10,
            "badge": "basic",
            "full_name": args[1],
            "primary_org_id": None,
            "mobile": None,
            "date_of_birth": None,
            "gender": None,
        }

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(
    auth: _Auth,
    *,
    storage: _Storage | None = None,
    db: _Db | None = None,
    role: str = "general_user",
) -> tuple[UUID, _Storage, _Db]:
    user = AuthenticatedUser(id=uuid4(), role=role, email="m@x.ph")
    storage = storage or _Storage()
    db = db or _Db()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_user] = lambda: user
    app.dependency_overrides[get_auth_client] = lambda: auth
    app.dependency_overrides[get_storage_client] = lambda: storage
    app.dependency_overrides[get_database] = lambda: db
    return user.id, storage, db


def test_a_resident_deletes_their_account_photos_first(client: TestClient) -> None:
    auth = _Auth()
    user_id, storage, db = _wire(auth)
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 204
    assert auth.calls == [("sign_in", "m@x.ph"), ("delete", str(user_id))]
    assert sorted(storage.removed) == sorted(
        f"national-ids/{user_id}/{name}" for name in ("national_id", "selfie", "national_id_qr")
    )
    audit = [args for query, args in db.executed if "insert into public.audit_logs" in query]
    assert len(audit) == 1 and "account.delete" in audit[0]


def test_a_wrong_password_deletes_nothing_and_is_not_a_401(client: TestClient) -> None:
    auth = _Auth()
    _, storage, db = _wire(auth)
    response = client.post("/auth/me/delete", json={"password": "guess"})
    assert response.status_code == 400
    assert response.json()["error"] == "wrong_password"
    assert [c for c, _ in auth.calls] == ["sign_in"]
    assert storage.removed == [] and db.executed == []


@pytest.mark.parametrize("role", ["sub_admin", "response_team", "admin"])
def test_a_staff_account_is_its_organizations(client: TestClient, role: str) -> None:
    auth = _Auth()
    _wire(auth, role=role)
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"] == "staff_account"
    assert auth.calls == []


def test_photos_that_cannot_go_keep_the_account(client: TestClient) -> None:
    auth = _Auth()
    _, _, db = _wire(auth, storage=_Storage(fails=True))
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 502
    assert response.json()["error"] == "account_delete_failed"
    assert [c for c, _ in auth.calls] == ["sign_in"]
    assert db.executed == []


def test_an_account_that_cannot_go_says_so(client: TestClient) -> None:
    auth = _Auth(delete_fails=True)
    _wire(auth)
    response = client.post("/auth/me/delete", json={"password": PASSWORD})
    assert response.status_code == 502
    assert response.json()["error"] == "account_delete_failed"


def test_sign_up_refuses_an_emoji_name_before_making_anything(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth)
    response = client.post(
        "/auth/signup",
        json={"email": "juan@gmail.com", "password": "password-123", "full_name": "Juan 😀"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_name"
    assert auth.calls == []


def test_sign_up_refuses_an_address_no_mail_reaches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ed.get_settings(), "email_deliverability_check", True)

    def undeliverable(email: str) -> None:
        raise EmailUndeliverableError("does not exist")

    monkeypatch.setattr(ed, "_check", undeliverable)
    auth = _Auth()
    _wire(auth)
    response = client.post(
        "/auth/signup",
        json={"email": "juan@qwerty-asdf.xyz", "password": "password-123", "full_name": "Juan"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "undeliverable_email"
    assert auth.calls == []


def test_sign_up_keeps_the_tidied_name(client: TestClient) -> None:
    auth = _Auth()
    _wire(auth)
    response = client.post(
        "/auth/signup",
        json={
            "email": "juan@gmail.com",
            "password": "password-123",
            "full_name": " Juan  Dela Cruz ",
        },
    )
    assert response.status_code == 201
    assert auth.calls[0][1]["data"] == {"full_name": "Juan Dela Cruz"}


def test_the_profile_refuses_an_emoji_name_and_tidies_a_good_one(client: TestClient) -> None:
    auth = _Auth()
    _, _, db = _wire(auth)
    bad = client.patch("/auth/me/profile", json={"full_name": "Juan 😀"})
    assert bad.status_code == 400
    assert bad.json()["error"] == "invalid_name"
    assert db.executed == []
    good = client.patch("/auth/me/profile", json={"full_name": "Ma.  Luisa"})
    assert good.status_code == 200
    assert good.json()["full_name"] == "Ma. Luisa"


# --------------------------------------------------------------------------- #
# Google Play copies and New Update!
# --------------------------------------------------------------------------- #
def test_a_play_copy_reads_its_version_and_is_not_told_of_github_releases() -> None:
    assert app_version_of("1.12.44 play") == (1, 12, 44)
    assert is_older("1.12.44 play", "1.12.45")
    assert "not like '% play'" in _DUE_SQL
