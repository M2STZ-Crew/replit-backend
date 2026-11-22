"""An Admin's responder accounts (hermetic, v1.12.49).

22 Nov 2026: "admin can manage responders too (because they are the most
powerful)", answered "Full account control" and "Own org; hub manages all".
What these pin:
- each Admin reaches its own organization's responders only, the central hub
  and the system Admin everyone's, and nobody else the routes at all;
- only responders: never a coordinator's, an Admin's or a resident's account;
- a link sets the password, never shown; a confirmed email is the responder's;
- only the hub moves one, within the agency and not while on a fire;
- every change writes the audit log, and none of it dispatches.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_current_user, get_database, get_email_client
from app.main import app
from app.schemas.auth import AuthenticatedUser

PASAY, MAKATI, POLICE, HUB, CLOSED = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
ORGS: dict[UUID, dict[str, Any]] = {
    PASAY: {"name": "Pasay Fire Volunteers", "agency_type": "fire_volunteer", "is_active": True},
    MAKATI: {"name": "Makati Fire Volunteers", "agency_type": "fire_volunteer", "is_active": True},
    POLICE: {"name": "PNP Pasay", "agency_type": "police", "is_active": True},
    HUB: {"name": "Barangay 76", "agency_type": "barangay", "is_active": True},
    CLOSED: {"name": "Closed Volunteers", "agency_type": "fire_volunteer", "is_active": False},
}


def _admin(org: UUID | None = PASAY, *, hub: bool = False, active: bool = True) -> Any:
    """An Admin of ``org``; with none, the system Admin."""
    if org is None:
        return AuthenticatedUser(id=uuid4(), role="admin", phone_verified=True)
    return AuthenticatedUser(
        id=uuid4(),
        role="admin",
        phone_verified=True,
        primary_org_id=org,
        org_name=ORGS[org]["name"],
        org_agency_type=ORGS[org]["agency_type"],
        org_is_active=active,
        org_is_central_hub=hub,
    )


class _Db:
    """The accounts, rosters and audit log, as far as these routes need them."""

    def __init__(self) -> None:
        self.users: dict[UUID, dict[str, Any]] = {}
        self.titles: dict[tuple[UUID, UUID], str | None] = {}
        self.roster_off: list[tuple[UUID, UUID]] = []
        self.audit: list[str] = []
        self.written: list[str] = []
        self.fail_profile = False

    def add(self, org: UUID | None = PASAY, **cols: Any) -> UUID:
        uid = uuid4()
        self.users[uid] = {
            "id": uid,
            "role": "response_team",
            "full_name": "Juan Dela Cruz",
            "email": "jdelacruz.firres@replit.com",
            "mobile": None,
            "agency_type": "fire_volunteer",
            "primary_org_id": org,
            "is_active": True,
            "created_at": datetime.now(UTC),
            "deactivated_at": None,
            "personal_email": "juan@gmail.com",
            "personal_email_verified": False,
            "responding": False,
            **cols,
        }
        return uid

    def _in_scope(self, user: dict[str, Any], scope: UUID | None) -> bool:
        return user["role"] == "response_team" and scope in (None, user["primary_org_id"])

    def _row(self, user: dict[str, Any]) -> dict[str, Any]:
        org = user["primary_org_id"]
        return {
            **user,
            "organization_id": org,
            "organization_name": ORGS[org]["name"] if org else None,
            "title": self.titles.get((org, user["id"])) if org else None,
            "created_by_name": None,
            "responding_area_id": uuid4() if user["responding"] else None,
            "responding_to": "Near F. Victor Street" if user["responding"] else None,
            "responding_since": datetime.now(UTC) if user["responding"] else None,
        }

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "lower(email) like" in query:
            stem, tail = args[0].split("%")
            emails = [str(u["email"]) for u in self.users.values()]
            return [{"email": e} for e in emails if e.startswith(stem) and e.endswith(tail)]
        if "update public.dispatch_logs" in query:
            self.written.append(query)
            was = self.users[args[0]]["responding"]
            self.users[args[0]]["responding"] = False
            return [{"area_id": uuid4()}] if was else []
        assert "u.role = 'response_team'" in query
        return [self._row(u) for u in self.users.values() if self._in_scope(u, args[0])]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "from public.organizations where id = $1" in query:
            org = ORGS.get(args[0])
            return {"id": args[0], **org} if org else None
        assert "u.role = 'response_team'" in query
        uid, scope = (args[0], args[1]) if "for update of u" in query else (args[1], args[0])
        user = self.users.get(uid)
        return self._row(user) if user and self._in_scope(user, scope) else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "select title from public.org_roster" in query:
            return self.titles.get((args[0], args[1]))
        if "from public.dispatch_logs" in query:
            return self.users[args[0]]["responding"]
        raise AssertionError(f"unexpected fetchval: {query[:90]}")

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if q.startswith("insert into public.audit_logs"):
            self.audit.append(args[3])
            return "INSERT 0 1"
        self.written.append(q)
        if q.startswith("update public.users set role = 'response_team'"):
            if self.fail_profile:
                return "UPDATE 0"
            self.users[args[0]].update(
                role="response_team",
                agency_type=args[1],
                primary_org_id=args[2],
                full_name=args[3],
                mobile=args[4],
                personal_email=args[6],
            )
        elif q.startswith("update public.users set full_name"):
            self.users[args[0]].update(full_name=args[1], mobile=args[2], primary_org_id=args[3])
        elif q.startswith("update public.users set personal_email"):
            if self.users[args[0]]["personal_email_verified"]:
                return "UPDATE 0"
            self.users[args[0]]["personal_email"] = args[1]
        elif q.startswith("update public.users set is_active = false"):
            self.users[args[0]]["is_active"] = False
        elif q.startswith("update public.users set is_active = true"):
            self.users[args[0]]["is_active"] = True
        elif q.startswith("insert into public.org_roster"):
            self.titles[(args[0], args[1])] = args[2]
        elif q.startswith("update public.org_roster set is_active = false"):
            self.roster_off.append((args[0], args[1]))
        elif "public.device_tokens" not in q:
            raise AssertionError(f"unexpected execute: {q[:90]}")
        return "UPDATE 1"


class _Auth:
    """Supabase Auth's admin calls, recorded."""

    def __init__(self, db: _Db) -> None:
        self.db = db
        self.passwords: list[str] = []
        self.updates: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.recovery: list[str] = []

    async def admin_create_user(self, *, email: str, password: str, **_: Any) -> dict[str, Any]:
        self.passwords.append(password)
        uid = self.db.add(None, email=email, role="general_user", agency_type=None)
        return {"id": str(uid)}

    async def admin_update_user(self, *, user_id: str, attributes: dict[str, Any]) -> Any:
        self.updates.append(attributes)
        return {}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)

    async def admin_generate_link(self, *, email: str, **_: Any) -> dict[str, Any]:
        self.recovery.append(email)
        return {"action_link": "https://auth.example/recover"}


class _Mail:
    """Brevo, recorded."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        if self.fail:
            from app.core.exceptions import AppError

            raise AppError("Brevo is down")
        self.sent.append((to, text or ""))


class _Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.db = _Db()
        self.auth = _Auth(self.db)
        self.mail = _Mail()
        app.dependency_overrides[get_database] = lambda: self.db
        app.dependency_overrides[get_auth_client] = lambda: self.auth
        app.dependency_overrides[get_email_client] = lambda: self.mail
        self.act_as(_admin())

    def act_as(self, user: AuthenticatedUser) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    def call(self, method: str, tail: str = "", body: Any = None) -> Any:
        return self.client.request(method, f"/admin/responders{tail}", json=body)


@pytest.fixture
def api() -> Iterator[_Api]:
    with TestClient(app) as client:
        yield _Api(client)
    app.dependency_overrides.clear()


NEW = {"first_name": "Maria", "last_name": "Santos", "personal_email": "Maria@Gmail.com"}


# --------------------------------------------------------------------------- #
# Who, and whose
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", ["general_user", "response_team", "sub_admin"])
def test_only_admins_reach_these_routes(api: _Api, role: str) -> None:
    api.act_as(
        AuthenticatedUser(
            id=uuid4(),
            role=role,
            agency_type=None if role == "general_user" else "fire_volunteer",
            primary_org_id=PASAY,
            phone_verified=True,
            email_verified=True,
        )
    )
    uid = api.db.add()
    assert api.call("GET").status_code == 403
    assert api.call("POST", body=NEW).status_code == 403
    assert api.call("POST", f"/{uid}/deactivate").status_code == 403
    assert not api.db.written


def test_an_admin_of_an_inactive_organization_changes_nothing(api: _Api) -> None:
    uid = api.db.add()
    api.act_as(_admin(active=False))
    assert api.call("GET").status_code == 403
    assert api.call("PATCH", f"/{uid}", {"title": "Nozzleman"}).status_code == 403
    assert not api.db.written


def test_an_admin_lists_its_own_the_hub_and_system_everyone(api: _Api) -> None:
    own = api.db.add(responding=True)
    other = api.db.add(MAKATI)
    nobody = api.db.add(None)
    api.db.add(role="sub_admin")  # never listed

    rows = api.call("GET").json()
    assert [r["id"] for r in rows] == [str(own)]
    assert rows[0]["responding"] and rows[0]["responding_to"] == "Near F. Victor Street"

    for admin in (_admin(HUB, hub=True), _admin(None)):
        api.act_as(admin)
        assert {r["id"] for r in api.call("GET").json()} == {str(own), str(other), str(nobody)}


@pytest.mark.parametrize(
    ("method", "tail", "body"),
    [
        ("PATCH", "", {"full_name": "Someone Else"}),
        ("POST", "/password-link", {"personal_email": "attacker@gmail.com"}),
        ("POST", "/deactivate", None),
        ("POST", "/reactivate", None),
    ],
)
def test_another_organization_s_responder_is_not_found(
    api: _Api, method: str, tail: str, body: Any
) -> None:
    uid = api.db.add(MAKATI)
    assert api.call(method, f"/{uid}{tail}", body).status_code == 404
    assert not api.db.written and not api.mail.sent and not api.auth.updates


@pytest.mark.parametrize("role", ["admin", "sub_admin", "general_user"])
def test_only_a_responder_s_account_even_for_the_system_admin(api: _Api, role: str) -> None:
    uid = api.db.add(role=role)
    api.act_as(_admin(None))
    sent = api.call("POST", f"/{uid}/password-link", {"personal_email": "me@gmail.com"})
    assert sent.status_code == 404
    assert api.call("POST", f"/{uid}/deactivate").status_code == 404
    assert not api.db.written and not api.mail.sent and not api.auth.updates


def test_none_of_the_routes_dispatches() -> None:
    paths = {p for p in app.openapi()["paths"] if p.startswith("/admin/responders")}
    assert paths == {
        "/admin/responders",
        "/admin/responders/email-preview",
        "/admin/responders/{user_id}",
        "/admin/responders/{user_id}/password-link",
        "/admin/responders/{user_id}/deactivate",
        "/admin/responders/{user_id}/reactivate",
    }


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_an_admin_creates_its_responder_and_never_sees_a_password(api: _Api) -> None:
    body = {**NEW, "title": " Nozzleman ", "mobile": "0917 123 4567"}
    res = api.call("POST", body=body)
    assert res.status_code == 201
    made = res.json()["responder"]
    assert made["email"] == "msantos.firres@replit.com"
    assert made["organization_id"] == str(PASAY) and made["agency_type"] == "fire_volunteer"
    assert made["title"] == "Nozzleman" and made["mobile"] == "+639171234567"
    assert api.auth.passwords[0] not in res.text
    assert api.mail.sent[0][0] == "maria@gmail.com"
    assert "Your organization's Admin" in api.mail.sent[0][1]
    assert "/auth/staff/password-link?token=" in api.mail.sent[0][1]
    assert res.json()["invite_email_sent"]
    assert api.db.audit == ["user.responder_created"]


def test_the_preview_numbers_a_taken_address(api: _Api) -> None:
    api.db.add()
    res = api.call("GET", "/email-preview?first_name=Jose&last_name=Dela%20Cruz")
    assert res.json()["email"] == "jdelacruz1.firres@replit.com"


def test_an_admin_cannot_create_into_another_organization(api: _Api) -> None:
    res = api.call("POST", body={**NEW, "organization_id": str(MAKATI)})
    assert res.status_code == 403
    assert not api.auth.passwords


def test_the_hub_creates_for_any_active_organization(api: _Api) -> None:
    api.act_as(_admin(HUB, hub=True))
    made = api.call("POST", body={**NEW, "organization_id": str(POLICE)}).json()["responder"]
    assert made["email"] == "msantos.polres@replit.com" and made["agency_type"] == "police"
    assert "A RepLiT Admin" in api.mail.sent[0][1]
    assert api.call("POST", body={**NEW, "organization_id": str(CLOSED)}).status_code == 409


def test_the_system_admin_names_the_organization(api: _Api) -> None:
    api.act_as(_admin(None))
    assert api.call("POST", body=NEW).status_code == 400
    assert not api.auth.passwords


@pytest.mark.parametrize(
    "bad",
    [
        {"personal_email": "maria.firres@replit.com"},
        {"personal_email": "maria@mailinator.com"},
        {"first_name": "M4ria"},
        {"mobile": "12345"},
    ],
)
def test_a_bad_field_makes_no_sign_in(api: _Api, bad: dict[str, str]) -> None:
    assert api.call("POST", body={**NEW, **bad}).status_code in (400, 422)
    assert not api.auth.passwords


def test_a_failed_profile_takes_the_sign_in_back(api: _Api) -> None:
    api.db.fail_profile = True
    assert api.call("POST", body=NEW).status_code >= 500
    assert len(api.auth.deleted) == 1
    assert not api.db.audit


def test_an_email_that_does_not_go_still_leaves_the_account(api: _Api) -> None:
    api.mail.fail = True
    res = api.call("POST", body=NEW)
    assert res.status_code == 201
    assert not res.json()["invite_email_sent"] and res.json()["detail"]


# --------------------------------------------------------------------------- #
# Edit and move
# --------------------------------------------------------------------------- #
def test_edit_name_title_and_mobile(api: _Api) -> None:
    uid = api.db.add()
    body = {"full_name": "Juan  P. Dela Cruz", "title": "Driver", "mobile": "09171234567"}
    row = api.call("PATCH", f"/{uid}", body).json()
    assert row["full_name"] == "Juan P. Dela Cruz"
    assert (row["title"], row["mobile"]) == ("Driver", "+639171234567")
    assert api.db.audit == ["user.responder_updated"]

    cleared = api.call("PATCH", f"/{uid}", {"title": "", "mobile": ""}).json()
    assert (cleared["title"], cleared["mobile"]) == (None, None)
    assert cleared["full_name"] == "Juan P. Dela Cruz"


def test_nothing_changed_records_nothing(api: _Api) -> None:
    uid = api.db.add()
    assert api.call("PATCH", f"/{uid}", {"full_name": "Juan Dela Cruz"}).status_code == 200
    assert not api.db.audit and not api.db.written


@pytest.mark.parametrize("name", [None, "", "Juan 2"])
def test_a_name_is_letters(api: _Api, name: str | None) -> None:
    uid = api.db.add()
    assert api.call("PATCH", f"/{uid}", {"full_name": name}).status_code == 400
    assert not api.db.written


def test_an_organization_s_admin_does_not_move_anyone(api: _Api) -> None:
    uid = api.db.add()
    assert api.call("PATCH", f"/{uid}", {"organization_id": str(MAKATI)}).status_code == 403
    assert not api.db.written


def test_the_hub_moves_within_the_agency_with_the_title(api: _Api) -> None:
    uid = api.db.add()
    api.db.titles[(PASAY, uid)] = "Driver"
    api.act_as(_admin(HUB, hub=True))
    row = api.call("PATCH", f"/{uid}", {"organization_id": str(MAKATI)}).json()
    assert (row["organization_id"], row["title"]) == (str(MAKATI), "Driver")
    assert api.db.roster_off == [(PASAY, uid)]
    assert api.db.audit == ["user.responder_moved"]


@pytest.mark.parametrize(
    ("to", "responding", "error"),
    [(POLICE, False, "other_agency"), (MAKATI, True, "responding")],
)
def test_no_move_across_agencies_or_during_a_fire(
    api: _Api, to: UUID, responding: bool, error: str
) -> None:
    uid = api.db.add(responding=responding)
    api.act_as(_admin(HUB, hub=True))
    res = api.call("PATCH", f"/{uid}", {"organization_id": str(to)})
    assert (res.status_code, res.json()["error"]) == (409, error)
    assert not api.db.written


def test_the_hub_gives_a_responder_with_no_organization_one(api: _Api) -> None:
    uid = api.db.add(None)
    api.act_as(_admin(HUB, hub=True))
    assert api.call("PATCH", f"/{uid}", {"title": "Driver"}).status_code == 400
    body = {"organization_id": str(PASAY), "title": "Driver"}
    row = api.call("PATCH", f"/{uid}", body).json()
    assert (row["organization_id"], row["title"]) == (str(PASAY), "Driver")


# --------------------------------------------------------------------------- #
# Password link
# --------------------------------------------------------------------------- #
def test_the_link_goes_to_their_own_email(api: _Api) -> None:
    uid = api.db.add()
    res = api.call("POST", f"/{uid}/password-link", {})
    assert res.json() == {"sent_to": "juan@gmail.com"}
    to, text = api.mail.sent[0]
    assert to == "juan@gmail.com"
    assert "/auth/staff/password-link?token=" in text
    assert "Your organization's Admin sent you a link" in text
    assert "We received a request" not in text
    assert not api.auth.updates  # the password they have still works
    assert api.db.audit == ["user.responder_password_link"]


def test_an_admin_fills_in_an_email_that_was_never_confirmed(api: _Api) -> None:
    uid = api.db.add(personal_email=None)
    assert api.call("POST", f"/{uid}/password-link", {}).status_code == 400
    body = {"personal_email": "Juan.New@Gmail.com"}
    assert api.call("POST", f"/{uid}/password-link", body).status_code == 200
    assert api.db.users[uid]["personal_email"] == "juan.new@gmail.com"
    assert api.mail.sent[0][0] == "juan.new@gmail.com"
    assert api.db.audit == ["user.responder_email_set", "user.responder_password_link"]


def test_a_confirmed_email_is_the_responder_s_to_change(api: _Api) -> None:
    uid = api.db.add(personal_email_verified=True)
    res = api.call("POST", f"/{uid}/password-link", {"personal_email": "attacker@gmail.com"})
    assert (res.status_code, res.json()["error"]) == (409, "personal_email_confirmed")
    assert api.db.users[uid]["personal_email"] == "juan@gmail.com"
    assert not api.mail.sent and not api.db.audit


def test_a_real_mailbox_sign_in_gets_its_own_link(api: _Api) -> None:
    uid = api.db.add(email="juan@yahoo.com", personal_email=None)
    body = {"personal_email": "attacker@gmail.com"}
    assert api.call("POST", f"/{uid}/password-link", body).status_code == 409
    assert api.call("POST", f"/{uid}/password-link", {}).json() == {"sent_to": "juan@yahoo.com"}
    assert api.auth.recovery == ["juan@yahoo.com"]


def test_no_link_for_an_account_that_is_off(api: _Api) -> None:
    uid = api.db.add(is_active=False)
    assert api.call("POST", f"/{uid}/password-link", {}).status_code == 409
    assert not api.mail.sent


def test_a_link_that_does_not_go_says_so(api: _Api) -> None:
    uid = api.db.add()
    api.mail.fail = True
    assert api.call("POST", f"/{uid}/password-link", {}).status_code == 502
    assert not api.db.audit


# --------------------------------------------------------------------------- #
# Off and on
# --------------------------------------------------------------------------- #
def test_off_releases_the_fire_and_on_lifts_the_ban(api: _Api) -> None:
    uid = api.db.add(responding=True)
    off = api.call("POST", f"/{uid}/deactivate").json()
    assert (off["is_active"], off["responding"]) == (False, False)
    on = api.call("POST", f"/{uid}/reactivate").json()
    assert on["is_active"]
    assert [u["ban_duration"] for u in api.auth.updates] == ["876000h", "none"]
    assert api.db.audit == ["user.responder_deactivated", "user.responder_reactivated"]
