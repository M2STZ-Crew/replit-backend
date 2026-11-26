"""Backend v1.12.53 (hermetic): only an organization going acts on a fire, only
BFP sets alarm levels, and the affiliation items still open on 26 Nov 2026.

- "the org can't mark fire out an incident if they're not going on that
  incident"; fire codes and alarm requests too (answered "Same rule");
- "central hub shouldn't raise an alarm" (answered "Ask BFP, like FV");
- the SEC certificate is really uploaded, privately ("Real private upload");
- a declined applicant is told, without the reason ("Polite email, no reason");
- an accepted organization sets up its own Admin ("One-time Admin link");
- accounts and organizations change only through the server ("Tighten").
"""

from __future__ import annotations

import inspect
import pathlib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_database, get_email_client, get_storage_client
from app.api.routes import affiliate_admin, affiliates, alarm_requests, fire_codes, incidents
from app.core.exceptions import ConflictError
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import access as A
from app.services.affiliate_links import ADMIN_FOR, CERTIFICATE_FOR, make_token
from app.services.incident import assert_org_going

MIGRATIONS = pathlib.Path(__file__).parent.parent / "supabase" / "migrations"


def _hub() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", primary_org_id=uuid4(), org_name="Barangay 76",
        org_agency_type="barangay", org_is_active=True, org_is_central_hub=True,
    )


# --------------------------------------------------------------------------- #
# Going
# --------------------------------------------------------------------------- #
class _Going:
    def __init__(self, going: bool) -> None:
        self.going = going
        self.asked: list[tuple[Any, ...]] = []

    async def fetchval(self, query: str, *args: Any) -> bool:
        assert "from public.dispatch_logs d" in query and "d.status = 'active'" in query
        self.asked.append(args)
        return self.going


async def test_an_organization_not_going_cannot_act() -> None:
    coordinator = AuthenticatedUser(
        id=uuid4(), role="sub_admin", agency_type="fire_volunteer", primary_org_id=uuid4()
    )
    with pytest.raises(ConflictError) as refused:
        await assert_org_going(_Going(False), uuid4(), coordinator, "mark it fire out")  # type: ignore[arg-type]
    assert refused.value.error_code == "not_going"
    assert "I am going" in refused.value.message
    db = _Going(True)
    await assert_org_going(db, uuid4(), coordinator, "mark it fire out")  # type: ignore[arg-type]
    # Their own dispatch, or anyone of their organization's.
    assert db.asked[0][1:] == (coordinator.id, coordinator.primary_org_id)


async def test_the_system_account_belongs_to_no_organization() -> None:
    db = _Going(False)
    await assert_org_going(db, uuid4(), AuthenticatedUser(id=uuid4(), role="admin"), "act")  # type: ignore[arg-type]
    assert not db.asked


@pytest.mark.parametrize(
    ("route", "act"),
    [
        (incidents.resolve_incident, '"mark it fire out"'),
        (fire_codes.press_fire_code, '"press fire codes on it"'),
        (alarm_requests.create_alarm_request, '"ask BFP to raise its alarm"'),
    ],
)
def test_fire_out_codes_and_asking_all_need_going(route: Any, act: str) -> None:
    assert "assert_org_going(db, " in inspect.getsource(route)
    assert act in inspect.getsource(route)


@pytest.mark.parametrize("route", [alarm_requests.raise_alarm])
def test_bfp_raises_from_anywhere(route: Any) -> None:
    # Answered "BFP raises from anywhere": raising and approving need no going.
    assert "assert_org_going" not in inspect.getsource(route)


# --------------------------------------------------------------------------- #
# Only BFP sets alarm levels
# --------------------------------------------------------------------------- #
def test_the_hub_asks_bfp_and_no_longer_raises() -> None:
    hub = A.admin_access(_hub())
    assert hub is not None
    assert hub.can(A.REQUEST_ALARM) and not hub.can(A.DECIDE_ALARM)
    assert not alarm_requests._may_decide(_hub())
    assert alarm_requests._may_request(_hub())


def test_the_database_lets_only_bfp_set_levels() -> None:
    sql = (MIGRATIONS / "20261126090000_only_bfp_sets_alarm_levels.sql").read_text(
        encoding="utf-8"
    )
    body = sql.split("as $$", 1)[1]
    assert "is_central_hub" not in body and "v_hub" not in body
    assert "v_agency = 'bfp'" in body and "v_org_agency = 'bfp'" in body
    assert "old.fire_type is null and new.fire_type is not null" in body


def test_writes_go_through_the_server() -> None:
    sql = (MIGRATIONS / "20261126090100_writes_through_the_server.sql").read_text(
        encoding="utf-8"
    )
    for policy in ("users_admin_all", "organizations_admin_all", "affiliate_requests_admin_all"):
        assert f"drop policy if exists {policy}" in sql
    assert "create policy" not in sql


# --------------------------------------------------------------------------- #
# The SEC certificate
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _Applications:
    def __init__(self, status: str = "pending", details: dict[str, Any] | None = None) -> None:
        self.id = uuid4()
        self.status = status
        self.details = details or {}
        self.updates: list[tuple[Any, ...]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "select status::text" in query:
            return self.status if args[0] == self.id else None
        if "select details" in query:
            return self.details if args[0] == self.id else None
        raise AssertionError(query)

    async def execute(self, query: str, *args: Any) -> str:
        assert "sec_certificate_path" in query
        self.updates.append(args)
        return "UPDATE 1"


class _Storage:
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    async def upload(self, **kw: Any) -> str:
        self.stored.append(kw)
        return str(kw["path"])

    async def create_signed_url(self, **kw: Any) -> str:
        return f"https://storage.example/{kw['bucket']}/{kw['path']}?signed"


def _wire(db: Any, storage: _Storage | None = None) -> _Storage:
    storage = storage or _Storage()
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_storage_client] = lambda: storage
    return storage


PDF = b"%PDF-1.7\n" + b"x" * 64


def test_the_certificate_is_stored_privately_for_that_application(client: TestClient) -> None:
    db = _Applications()
    storage = _wire(db)
    token = make_token(db.id, "certificate", CERTIFICATE_FOR)
    response = client.post(
        f"/affiliates/register/{db.id}/certificate",
        data={"token": token},
        files={"file": ("sec.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    (stored,) = storage.stored
    assert stored["bucket"] == "affiliate-documents"
    assert stored["path"] == f"{db.id}/certificate.pdf"
    assert stored["content_type"] == "application/pdf"
    assert db.updates[0][1:] == (f"{db.id}/certificate.pdf", "application/pdf")


@pytest.mark.parametrize(
    ("body", "status", "why"),
    [
        (b"MZ\x90\x00 not a certificate", 400, "unsupported_file"),
        (PDF + b"x" * (10 * 1024 * 1024), 400, "too_large"),
    ],
    ids=["not a certificate", "too large"],
)
def test_what_the_upload_refuses(client: TestClient, body: bytes, status: int, why: str) -> None:
    db = _Applications()
    storage = _wire(db)
    token = make_token(db.id, "certificate", CERTIFICATE_FOR)
    response = client.post(
        f"/affiliates/register/{db.id}/certificate",
        data={"token": token},
        files={"file": ("sec.pdf", body, "application/pdf")},
    )
    assert (response.status_code, response.json()["error"]) == (status, why)
    assert not storage.stored


def test_a_token_for_another_application_or_out_of_date_is_refused(client: TestClient) -> None:
    db = _Applications()
    storage = _wire(db)
    for token in (
        make_token(uuid4(), "certificate", CERTIFICATE_FOR),
        make_token(db.id, "certificate", timedelta(seconds=-1)),
        make_token(db.id, "admin", ADMIN_FOR),
    ):
        response = client.post(
            f"/affiliates/register/{db.id}/certificate",
            data={"token": token},
            files={"file": ("sec.pdf", PDF, "application/pdf")},
        )
        assert response.status_code == 403
    assert not storage.stored


def test_only_the_hub_opens_it_through_a_short_link(client: TestClient) -> None:
    db = _Applications(details={"sec_certificate_path": "x/certificate.pdf"})
    _wire(db)
    reviewer = affiliates.AffiliateReviewer.__metadata__[0].dependency
    app.dependency_overrides[reviewer] = _hub
    response = client.get(f"/affiliates/{db.id}/certificate")
    assert response.status_code == 200
    assert response.json()["url"].endswith("x/certificate.pdf?signed")


# --------------------------------------------------------------------------- #
# The one-time Admin link
# --------------------------------------------------------------------------- #
class _Org:
    def __init__(self, *, has_admin: bool = False, taken: set[str] | None = None) -> None:
        self.id = uuid4()
        self.has_admin = has_admin
        self.taken = taken or set()
        self.profile: dict[str, Any] = {}
        self.audit: list[str] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Org]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if args[0] != self.id:
            return None
        return {"id": self.id, "name": "Hercules Fire Brigade", "is_active": True}

    async def fetchval(self, query: str, *args: Any) -> bool:
        if "lower(email) = lower($1)" in query:
            return str(args[0]).lower() in self.taken
        assert "role::text = 'admin'" in query
        return self.has_admin

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if q.startswith("insert into public.audit_logs"):
            self.audit.append(args[3])
        elif q.startswith("update public.users set role = 'admin'"):
            self.profile = {"id": args[0], "org": args[1], "name": args[2], "personal": args[3]}
        return "OK"


class _Auth:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []

    async def admin_create_user(self, *, email: str, **_: Any) -> dict[str, Any]:
        self.created.append(email)
        return {"id": str(uuid4())}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **message: Any) -> None:
        self.sent.append(message)


def _admin_wire(org: _Org) -> tuple[_Auth, _Mail]:
    auth, mail = _Auth(), _Mail()
    app.dependency_overrides[get_database] = lambda: org
    app.dependency_overrides[get_auth_client] = lambda: auth
    app.dependency_overrides[get_email_client] = lambda: mail
    return auth, mail


def _link(org: _Org, lasts: timedelta = ADMIN_FOR) -> str:
    return make_token(org.id, "admin", lasts, email="captain@brigade.example.com")


def test_the_link_says_where_it_stands(client: TestClient) -> None:
    org = _Org()
    _admin_wire(org)
    page = client.get("/affiliates/admin-registration", params={"token": _link(org)}).json()
    assert (page["state"], page["organization"], page["suffix"]) == (
        "valid", "Hercules Fire Brigade", ".admin@replit.com"
    )
    expired = client.get(
        "/affiliates/admin-registration", params={"token": _link(org, timedelta(seconds=-5))}
    )
    assert expired.json()["state"] == "expired"
    org.has_admin = True
    assert client.get(
        "/affiliates/admin-registration", params={"token": _link(org)}
    ).json()["state"] == "used"
    nonsense = client.get("/affiliates/admin-registration", params={"token": "nonsense"})
    assert nonsense.status_code == 404


@pytest.mark.parametrize(
    ("prefix", "status"),
    [
        ("hercules", "available"),
        ("taken", "taken"),
        ("admin", "not_allowed"),
        ("a!", "not_allowed"),
    ],
)
def test_the_prefix_is_checked(client: TestClient, prefix: str, status: str) -> None:
    org = _Org(taken={"taken.admin@replit.com"})
    _admin_wire(org)
    answer = client.get(
        "/affiliates/admin-registration/check", params={"token": _link(org), "prefix": prefix}
    )
    assert answer.json()["status"] == status


def test_the_admin_is_made_and_emailed_a_password_link(client: TestClient) -> None:
    org = _Org()
    auth, mail = _admin_wire(org)
    response = client.post(
        "/affiliates/admin-registration", json={"token": _link(org), "prefix": "Hercules"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "hercules.admin@replit.com"
    assert auth.created == ["hercules.admin@replit.com"]
    assert org.profile["org"] == org.id and org.profile["personal"] == "captain@brigade.example.com"
    assert org.audit == ["user.admin_registered"]
    (sent,) = mail.sent
    assert sent["to"] == "captain@brigade.example.com"
    assert "/auth/staff/password-link?token=" in sent["text"]
    assert "Admin console" in sent["text"]


@pytest.mark.parametrize(("used", "error"), [(True, "link_used"), (False, "taken")])
def test_once_and_never_on_a_taken_sign_in(client: TestClient, used: bool, error: str) -> None:
    org = _Org(has_admin=used, taken={"hercules.admin@replit.com"})
    auth, _ = _admin_wire(org)
    response = client.post(
        "/affiliates/admin-registration", json={"token": _link(org), "prefix": "hercules"}
    )
    assert (response.status_code, response.json()["error"]) == (409, error)
    assert not auth.created


def test_reserved_and_malformed_prefixes() -> None:
    assert affiliate_admin.prefix_allowed("brgy-183")
    for bad in ("bfp", "admin", "ab", "-abc", "abc-", "UPPER", "a" * 31):
        assert not affiliate_admin.prefix_allowed(bad)


def test_the_bucket_is_private() -> None:
    sql = (MIGRATIONS / "20261126090200_affiliate_documents.sql").read_text(encoding="utf-8")
    assert "'affiliate-documents'" in sql and "false" in sql


def test_a_decline_tells_the_applicant_without_the_reason() -> None:
    message = affiliates._declined_email()
    assert "not approved" in message.text
    assert "apply again" in message.text


def _uuid(value: str) -> UUID:
    return UUID(value)
