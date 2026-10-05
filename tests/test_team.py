"""A coordinator's responder accounts (hermetic, v1.12.4).

What these pin:
- the address follows the account directory: first initial + full surname,
  ``.res`` + the agency, ``@replit.com``; numbered after the surname when the
  same role already has that name, the first keeping the plain address;
- a coordinator makes responders of their own agency and team only, and only a
  sub-admin can;
- the password is generated, strong, and returned once;
- deactivating bans the sign-in, releases a live response, stops pushes and
  keeps the account; a deactivated account is refused on every request.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_current_user, get_database
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services.responder_accounts import (
    InvalidNameError,
    local_base,
    responder_email,
    responder_suffix,
    temporary_password,
)

ORG = uuid4()


# --------------------------------------------------------------------------- #
# The address rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("agency", "email"),
    [
        ("fire_volunteer", "jdelacruz.resfir@replit.com"),
        ("bfp", "jdelacruz.resbfp@replit.com"),
        ("police", "jdelacruz.respol@replit.com"),
        ("medical", "jdelacruz.resmed@replit.com"),
        ("barangay", "jdelacruz.resbar@replit.com"),
    ],
)
def test_the_address_is_initial_surname_role_and_agency(agency: str, email: str) -> None:
    assert responder_email("Juan", "Dela Cruz", agency, []) == email


def test_the_directory_examples() -> None:
    assert responder_email("Bhora", "Thitot", "police", []) == "bthitot.respol@replit.com"
    assert responder_email("Sakura", "Haruno", "medical", []) == "sharuno.resmed@replit.com"
    assert responder_email("Lolo", "Donat", "barangay", []) == "ldonat.resbar@replit.com"


def test_accents_spaces_and_case_are_flattened() -> None:
    assert local_base("Ñino", "Peña-Santos") == "npenasantos"
    assert local_base("  maria ", "DE LOS REYES") == "mdelosreyes"


def test_a_name_with_no_letters_is_refused() -> None:
    with pytest.raises(InvalidNameError):
        local_base("Juan", "123")


def test_the_first_keeps_the_plain_address_and_later_ones_are_numbered() -> None:
    taken = ["jmoral.resbar@replit.com"]
    assert responder_email("Justine", "Moral", "barangay", taken) == (
        "jmoral1.resbar@replit.com"
    )
    taken.append("jmoral1.resbar@replit.com")
    assert responder_email("Jose", "Moral", "barangay", taken) == "jmoral2.resbar@replit.com"


def test_numbers_count_only_the_same_role_and_name() -> None:
    taken = [
        "jmoral.obsbar@replit.com",  # an observer, not a responder
        "jmoral.respol@replit.com",  # a police responder
        "jmorales.resbar@replit.com",  # a different surname
    ]
    assert responder_email("Justine", "Moral", "barangay", taken) == (
        "jmoral.resbar@replit.com"
    )


def test_numbers_run_on_rather_than_refill() -> None:
    # jmoral1 was removed; the next is still after the highest.
    taken = ["jmoral.resbar@replit.com", "jmoral2.resbar@replit.com"]
    assert responder_email("J", "Moral", "barangay", taken) == "jmoral3.resbar@replit.com"


def test_no_responders_for_an_unknown_agency() -> None:
    with pytest.raises(ValueError):
        responder_suffix("coastguard")


def test_the_temporary_password_is_strong_and_readable() -> None:
    seen = {temporary_password() for _ in range(50)}
    assert len(seen) == 50
    for pw in seen:
        assert re.fullmatch(r"[A-Za-z2-9]{4}-[A-Za-z2-9]{4}-[A-Za-z2-9]{4}", pw)
        assert not set(pw) & set("0O1lI")
        assert any(c.isupper() for c in pw) and any(c.islower() for c in pw)
        assert any(c.isdigit() for c in pw)


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
def _coordinator(agency: str = "barangay", role: str = "sub_admin") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role=role, agency_type=agency, primary_org_id=ORG, phone_verified=True
    )


class _Conn:
    def __init__(self, db: _Db) -> None:
        self.db = db

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return await self.db.fetchrow(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return await self.db.fetch(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self.db.execute(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield


class _Db:
    """public.users and the audit log, as far as the team routes need them."""

    def __init__(self) -> None:
        self.users: dict[UUID, dict[str, Any]] = {}
        self.audit: list[str] = []
        self.dispatches_released = 0
        self.tokens_off = 0

    def add(self, email: str, **cols: Any) -> UUID:
        uid = uuid4()
        self.users[uid] = {
            "id": uid,
            "email": email,
            "full_name": cols.get("full_name"),
            "mobile": None,
            "role": cols.get("role", "response_team"),
            "agency_type": cols.get("agency_type", "barangay"),
            "primary_org_id": cols.get("primary_org_id", ORG),
            "is_active": cols.get("is_active", True),
            "created_at": datetime.now(UTC),
            "deactivated_at": None,
            "responding": cols.get("responding", False),
        }
        return uid

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        yield _Conn(self)

    def _row(self, u: dict[str, Any]) -> dict[str, Any]:
        return {k: u[k] for k in (
            "id", "full_name", "email", "mobile", "agency_type", "is_active",
            "created_at", "deactivated_at", "responding",
        )}

    def _in_scope(self, u: dict[str, Any], agency: str, org: Any) -> bool:
        return (
            u["role"] == "response_team"
            and u["agency_type"] == agency
            and u["primary_org_id"] == org
        )

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "lower(email) like" in query:
            pattern = re.escape(args[0]).replace("%", ".*")
            return [
                {"email": u["email"]}
                for u in self.users.values()
                if re.fullmatch(pattern, u["email"].lower())
            ]
        if "update public.dispatch_logs" in query:
            uid = args[0]
            if self.users[uid]["responding"]:
                self.users[uid]["responding"] = False
                self.dispatches_released += 1
                return [{"area_id": uuid4()}]
            return []
        agency, org = args[0], args[1]
        return [self._row(u) for u in self.users.values() if self._in_scope(u, agency, org)]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if query.lstrip().startswith("update public.users"):
            uid, agency, full_name, org, mobile, _by = args
            u = self.users[uid]
            u.update(
                role="response_team", agency_type=agency, full_name=full_name,
                primary_org_id=org, mobile=mobile, is_active=True,
            )
            return self._row(u)
        agency, org, uid = args
        u = self.users.get(uid)
        return self._row(u) if u and self._in_scope(u, agency, org) else None

    async def execute(self, query: str, *args: Any) -> str:
        if "insert into public.audit_logs" in query:
            self.audit.extend(a for a in args if isinstance(a, str) and a.startswith("user."))
        elif "device_tokens" in query:
            self.tokens_off += 1
        elif "set is_active = false" in query:
            self.users[args[0]]["is_active"] = False
            self.users[args[0]]["deactivated_at"] = datetime.now(UTC)
        elif "set is_active = true" in query:
            self.users[args[0]]["is_active"] = True
            self.users[args[0]]["deactivated_at"] = None
        return "OK"


class _Auth:
    """Supabase Auth's admin calls, recorded. Creating makes the profile row,
    as the handle_new_user trigger does."""

    def __init__(self, db: _Db) -> None:
        self.db = db
        self.created: list[tuple[str, str]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[str] = []
        self.race_on: str | None = None

    async def admin_create_user(self, *, email: str, password: str | None = None, **_: Any) -> Any:
        if email == self.race_on:
            self.race_on = None
            self.db.add(email, role="general_user")
            raise BadRequestError("A user with this email address has already been registered")
        assert password is not None
        self.created.append((email, password))
        uid = self.db.add(email, role="general_user", agency_type=None, primary_org_id=None)
        return {"id": str(uid)}

    async def admin_update_user(self, *, user_id: str, attributes: dict[str, Any]) -> Any:
        self.updates.append((user_id, attributes))
        return {}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(user: AuthenticatedUser, db: _Db, auth: _Auth) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_auth_client] = lambda: auth


def test_a_coordinator_creates_a_responder_of_their_agency_and_team(
    client: TestClient,
) -> None:
    db = _Db()
    db.add("ldonat.resbar@replit.com", full_name="Lolo Donat")
    auth = _Auth(db)
    coordinator = _coordinator("barangay")
    _wire(coordinator, db, auth)

    resp = client.post(
        "/team/responders",
        json={"first_name": "Lito", "last_name": "Donat", "mobile": "0917 123 4567"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "ldonat1.resbar@replit.com", "the second Lito/Lolo Donat"
    assert body["temporary_password"] == auth.created[0][1]
    responder = body["responder"]
    assert responder["agency_type"] == "barangay" and responder["is_active"] is True
    assert responder["full_name"] == "Lito Donat"
    assert responder["mobile"] == "+639171234567"
    made = db.users[UUID(responder["id"])]
    assert made["role"] == "response_team" and made["primary_org_id"] == ORG
    assert db.audit == ["user.responder_created"]


def test_a_race_for_the_address_takes_the_next_number(client: TestClient) -> None:
    db = _Db()
    auth = _Auth(db)
    auth.race_on = "bthitot.respol@replit.com"
    _wire(_coordinator("police"), db, auth)
    resp = client.post("/team/responders", json={"first_name": "Bhora", "last_name": "Thitot"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "bthitot1.respol@replit.com"


def test_the_preview_shows_the_address_the_name_would_get(client: TestClient) -> None:
    db = _Db()
    db.add("sharuno.resmed@replit.com", agency_type="medical")
    _wire(_coordinator("medical"), db, _Auth(db))
    resp = client.get(
        "/team/responders/email-preview",
        params={"first_name": "Sasuke", "last_name": "Haruno"},
    )
    assert resp.json() == {"email": "sharuno1.resmed@replit.com"}


@pytest.mark.parametrize("role", ["response_team", "general_user", "admin"])
def test_only_a_sub_admin_makes_responders(client: TestClient, role: str) -> None:
    db = _Db()
    user = AuthenticatedUser(
        id=uuid4(),
        role=role,
        agency_type="fire_volunteer" if role == "response_team" else None,
        phone_verified=True,
    )
    _wire(user, db, _Auth(db))
    resp = client.post("/team/responders", json={"first_name": "A", "last_name": "B"})
    assert resp.status_code == 403
    assert not db.users


def test_the_roster_is_the_coordinator_s_own_team_and_agency(client: TestClient) -> None:
    db = _Db()
    mine = db.add("amine.resbar@replit.com")
    db.add("bother.resbar@replit.com", primary_org_id=uuid4())  # another team
    db.add("cpolice.respol@replit.com", agency_type="police")  # another agency
    db.add("dcaptain.corbar@replit.com", role="sub_admin")  # not a responder
    _wire(_coordinator("barangay"), db, _Auth(db))
    ids = [r["id"] for r in client.get("/team/responders").json()]
    assert ids == [str(mine)]


def test_another_team_s_responder_cannot_be_touched(client: TestClient) -> None:
    db = _Db()
    theirs = db.add("bother.resbar@replit.com", primary_org_id=uuid4())
    auth = _Auth(db)
    _wire(_coordinator("barangay"), db, auth)
    for action in ("reset-password", "deactivate", "reactivate"):
        assert client.post(f"/team/responders/{theirs}/{action}").status_code == 404
    assert not auth.updates


def test_reset_password_gives_a_new_one_once(client: TestClient) -> None:
    db = _Db()
    rid = db.add("amine.resbar@replit.com")
    auth = _Auth(db)
    _wire(_coordinator("barangay"), db, auth)
    resp = client.post(f"/team/responders/{rid}/reset-password")
    assert resp.status_code == 200, resp.text
    new = resp.json()["temporary_password"]
    assert auth.updates == [(str(rid), {"password": new})]


def test_deactivate_bans_releases_and_keeps_the_account(client: TestClient) -> None:
    db = _Db()
    rid = db.add("amine.resbar@replit.com", responding=True)
    auth = _Auth(db)
    _wire(_coordinator("barangay"), db, auth)

    resp = client.post(f"/team/responders/{rid}/deactivate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False
    assert auth.updates[0][1]["ban_duration"] != "none"
    assert db.audit == ["user.responder_deactivated"]
    assert db.dispatches_released == 1 and db.tokens_off == 1
    assert rid in db.users, "kept, with its history"

    # A deactivated account gets no new password until it is reactivated.
    assert client.post(f"/team/responders/{rid}/reset-password").status_code == 409

    resp = client.post(f"/team/responders/{rid}/reactivate")
    assert resp.json()["is_active"] is True
    assert auth.updates[-1][1] == {"ban_duration": "none"}


async def test_a_deactivated_account_is_refused_on_every_request() -> None:
    from app.api import deps

    class _OneUser:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            assert "is_active" in query
            return {
                "id": uuid4(), "email": "x.resbar@replit.com", "phone": None,
                "role": "response_team", "agency_type": "barangay",
                "verified_percent": 0, "badge": "yellow", "full_name": "X",
                "primary_org_id": None, "mobile": None, "date_of_birth": None,
                "gender": None, "phone_verified": False, "is_active": False,
            }

    class _Creds:
        credentials = "token"

    class _Req:
        class state:  # noqa: N801
            pass

    async def _claims(token: str, client: Any) -> dict[str, str]:
        return {"sub": str(uuid4())}

    original = deps.decode_access_token
    deps.decode_access_token = _claims  # type: ignore[assignment]
    try:
        with pytest.raises(UnauthorizedError, match="deactivated"):
            await deps.get_current_user(
                _Req(), _Creds(), _OneUser(), None  # type: ignore[arg-type]
            )
    finally:
        deps.decode_access_token = original  # type: ignore[assignment]
