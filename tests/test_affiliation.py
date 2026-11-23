"""Affiliation, from the form to the first Coordinator (hermetic, v1.12.51).

23 Nov 2026: "can you please check the whole affiliation thing because it has
not been check since release". What these pin:
- accepting never touches an account that exists, whatever its role or email;
- the organization and its Coordinator are made together, once, or not at all;
- the form's text cannot break an email, or fill the mail server's allowance;
- every decision is in the audit log;
- a suspended or revoked organization gets no socket and no alerts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_client, get_current_user, get_database, get_email_client
from app.api.routes import affiliate_standing, affiliates, ws
from app.core.exceptions import AppError, BadRequestError, ConflictError
from app.main import app
from app.realtime.manager import ConnectionManager
from app.schemas.affiliate import AffiliateAcceptRequest, AffiliatePublicRegister
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import OrganizationDelete
from app.services import alarm_notify, fire_code_notify, incident_notify
from app.workers import coordinator_pings

CONTACT = "captain@brigade.example.com"
MADE = "rdizon.fircor@replit.com"


def _reviewer(*, hub: bool = True) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        role="admin",
        phone_verified=True,
        primary_org_id=uuid4(),
        org_name="Barangay 76" if hub else "Pasay Fire Volunteers",
        org_agency_type="barangay" if hub else "fire_volunteer",
        org_is_active=True,
        org_is_central_hub=hub,
    )


class _Db:
    """The application, the accounts and the organizations, with transactions
    that take turns and roll back."""

    def __init__(self, **application: Any) -> None:
        now = datetime.now(UTC)
        self.id = uuid4()
        self.application: dict[str, Any] = {
            "id": self.id,
            "organization_name": "Hercules Fire Brigade",
            "agency_type": "fire_volunteer",
            "requested_by": None,
            "contact_name": "Ramon Dizon",
            "contact_email": CONTACT,
            "contact_phone": "02 8123 4567",
            "address": "1 Sample St, Pasay",
            "message": None,
            "status": "pending",
            "organization_id": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_notes": None,
            "details": json.dumps({"contact_first_name": "Ramon", "contact_last_name": "Dizon"}),
            "created_at": now,
            "updated_at": now,
            **application,
        }
        self.users: dict[UUID, dict[str, Any]] = {}
        self.orgs: dict[UUID, dict[str, Any]] = {}
        self.audit: list[str] = []
        self.roster: list[tuple[UUID, UUID]] = []
        self.fail_profile = False
        self.lock = asyncio.Lock()
        self.inside = False

    def add(self, **columns: Any) -> UUID:
        uid = uuid4()
        self.users[uid] = {"role": "general_user", "primary_org_id": None, **columns}
        return uid

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.lock:
            kept = deepcopy((self.application, self.users, self.orgs, self.audit))
            self.inside = True
            try:
                yield
            except Exception:
                self.application, self.users, self.orgs, self.audit = kept
                raise
            finally:
                self.inside = False

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        assert "lower(email) like" in query, query
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        row = dict(self.application) if args[0] == self.id else None
        await asyncio.sleep(0)
        if row is None:
            return None
        if "set status = 'approved'" in query:
            assert self.inside
            self.application.update(
                status="approved", organization_id=args[1], reviewed_by=args[2]
            )
            return dict(self.application)
        if "set status = 'rejected'" in query:
            assert self.inside
            if self.application["status"] != "pending":
                return None
            self.application.update(status="rejected", review_notes=args[2])
            return dict(self.application)
        assert query.lstrip().startswith("select"), query
        return row

    async def fetchval(self, query: str, *args: Any) -> Any:
        assert self.inside, "decided outside its transaction"
        if "for update" in query:
            return self.application["status"]
        assert "insert into public.organizations" in query, query
        org = uuid4()
        self.orgs[org] = {
            "name": args[0], "agency_type": args[1], "email": args[2],
            "phone": args[3], "address": args[4],
        }
        return org

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        assert self.inside, q
        if q.startswith("insert into public.audit_logs"):
            self.audit.append(args[3])
        elif q.startswith("update public.users set role = 'sub_admin'"):
            if self.fail_profile:
                return "UPDATE 0"
            self.users[args[0]].update(
                role="sub_admin", agency_type=args[1], primary_org_id=args[2],
                full_name=args[3], created_by=args[5], personal_email=args[6],
            )
        elif q.startswith("insert into public.org_roster"):
            self.roster.append((args[0], args[1]))
        else:
            raise AssertionError(q)
        return "UPDATE 1"


class _Auth:
    """Only what accepting may call. An update or a link would be an AttributeError."""

    def __init__(self, db: _Db) -> None:
        self.db = db
        self.created: list[str] = []
        self.deleted: list[str] = []

    async def admin_create_user(self, *, email: str, **_: Any) -> dict[str, Any]:
        self.created.append(email)
        return {"id": str(self.db.add(email=email))}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)


class _Mail:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, str]] = []

    async def send(self, **message: Any) -> None:
        if self.fail:
            raise AppError("Brevo is down")
        # As Brevo's client builds it: a line break in a header is a ValueError.
        EmailMessage()["Subject"] = message["subject"]
        self.sent.append(message)


async def _accept(
    db: _Db,
    auth: _Auth | None = None,
    mail: _Mail | None = None,
    admin: AuthenticatedUser | None = None,
    **body: Any,
) -> Any:
    return await affiliates.accept_affiliate_request(
        db.id,
        AffiliateAcceptRequest(**body),
        None,  # type: ignore[arg-type]
        admin or _reviewer(),
        db,  # type: ignore[arg-type]
        auth or _Auth(db),  # type: ignore[arg-type]
        mail or _Mail(),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Accounts that exist are never touched
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "existing",
    [
        pytest.param({"role": "general_user", "email_verified": False}, id="unconfirmed"),
        pytest.param({"role": "general_user", "email_verified": True}, id="resident"),
        pytest.param({"role": "response_team", "primary_org_id": uuid4()}, id="another's staff"),
        pytest.param({"role": "sub_admin", "primary_org_id": uuid4()}, id="another's coordinator"),
        pytest.param({"role": "admin", "primary_org_id": uuid4()}, id="an admin"),
    ],
)
async def test_accepting_never_touches_the_account_with_that_email(
    existing: dict[str, Any],
) -> None:
    db = _Db()
    uid = db.add(email=CONTACT, **existing)
    before = dict(db.users[uid])
    auth, mail = _Auth(db), _Mail()

    result = await _accept(db, auth, mail)

    assert db.users[uid] == before
    assert auth.created == [MADE]
    (new,) = [u for u in db.users.values() if u["email"] == MADE]
    assert new["role"] == "sub_admin"
    assert new["primary_org_id"] == result.request.organization_id
    assert new["personal_email"] == CONTACT and new["full_name"] == "Ramon Dizon"


async def test_the_link_goes_to_the_contact_and_confirms_it() -> None:
    db, mail = _Db(), _Mail()

    result = await _accept(db, mail=mail)

    (sent,) = mail.sent
    assert sent["to"] == CONTACT
    assert "/auth/staff/password-link?token=" in sent["text"]
    assert MADE in sent["text"] and "central hub" in sent["text"]
    assert "reportwhatslit-apk.vercel.app" in sent["text"]
    assert (result.account_email, result.sign_in_address) == (CONTACT, MADE)
    assert result.account_provisioned and result.account_created and result.invite_email_sent


# --------------------------------------------------------------------------- #
# Together, once, or not at all
# --------------------------------------------------------------------------- #
async def test_the_organization_the_roster_and_the_audit() -> None:
    db = _Db()

    await _accept(db)

    ((org_id, org),) = db.orgs.items()
    assert org["address"] == "1 Sample St, Pasay" and org["phone"] == "02 8123 4567"
    assert [o for o, _ in db.roster] == [org_id]
    assert db.audit == ["affiliate.accept", "user.coordinator_created"]


async def test_two_accepts_at_once_make_one_organization() -> None:
    db = _Db()
    auth = _Auth(db)

    results = await asyncio.gather(
        _accept(db, auth), _accept(db, auth), return_exceptions=True
    )

    assert len(db.orgs) == 1
    assert sum(isinstance(r, ConflictError) for r in results) == 1
    assert len(auth.created) == 2 and len(auth.deleted) == 1
    assert db.audit == ["affiliate.accept", "user.coordinator_created"]


async def test_a_failed_profile_leaves_nothing_behind() -> None:
    db = _Db()
    db.fail_profile = True
    auth, mail = _Auth(db), _Mail()

    with pytest.raises(AppError):
        await _accept(db, auth, mail)

    assert db.application["status"] == "pending"
    assert not db.orgs and not db.audit and not mail.sent
    assert len(auth.deleted) == 1


async def test_a_failed_email_keeps_both_and_says_so() -> None:
    db = _Db()

    result = await _accept(db, mail=_Mail(fail=True))

    assert len(db.orgs) == 1 and result.account_provisioned
    assert not result.invite_email_sent and "Forgot password" in result.detail


async def test_a_reviewed_application_is_refused() -> None:
    db = _Db(status="rejected")
    auth = _Auth(db)
    with pytest.raises(ConflictError):
        await _accept(db, auth)
    assert not auth.created and not db.orgs


async def test_an_older_application_needs_a_name_from_the_hub() -> None:
    db = _Db(details=None)
    auth = _Auth(db)
    with pytest.raises(BadRequestError) as refused:
        await _accept(db, auth)
    assert refused.value.error_code == "coordinator_name_needed"
    assert not auth.created and not db.orgs

    await _accept(db, auth, coordinator_first_name="Liza", coordinator_last_name="Peña")
    assert auth.created == ["lpena.fircor@replit.com"]


async def test_the_hub_may_correct_the_name() -> None:
    db = _Db()
    auth = _Auth(db)
    await _accept(db, auth, coordinator_first_name="Ana", coordinator_last_name="Dela Cruz")
    assert auth.created == ["adelacruz.fircor@replit.com"]


@pytest.mark.parametrize("name", ["R4mon", "Ramon 🔥"])
async def test_a_coordinator_s_name_is_letters(name: str) -> None:
    db = _Db()
    auth = _Auth(db)
    with pytest.raises(BadRequestError):
        await _accept(db, auth, coordinator_first_name=name)
    assert not auth.created


async def test_a_made_address_is_no_contact() -> None:
    db = _Db(contact_email="obryan.fircor@replit.com")
    auth = _Auth(db)
    with pytest.raises(BadRequestError):
        await _accept(db, auth)
    assert not auth.created and not db.orgs


async def test_no_email_makes_the_organization_alone() -> None:
    db = _Db(contact_email=None, details=None)
    auth = _Auth(db)
    result = await _accept(db, auth)
    assert len(db.orgs) == 1 and not auth.created
    assert not result.account_provisioned and "Accounts" in result.detail


async def test_a_line_break_in_the_name_cannot_break_the_email() -> None:
    db, mail = _Db(organization_name="Hercules\r\nBcc: x@example.com"), _Mail()
    result = await _accept(db, mail=mail)
    assert result.invite_email_sent
    assert "\n" not in mail.sent[0]["subject"]


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _serve(db: Any, admin: AuthenticatedUser | None = None) -> _Mail:
    mail = _Mail()
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_auth_client] = lambda: _Auth(db)
    app.dependency_overrides[get_email_client] = lambda: mail
    if admin is not None:
        app.dependency_overrides[get_current_user] = lambda: admin
    return mail


def test_only_the_hub_accepts_or_declines(client: TestClient) -> None:
    db = _Db()
    _serve(db, _reviewer(hub=False))
    assert client.post(f"/affiliates/{db.id}/accept", json={}).status_code == 403
    assert client.post(f"/affiliates/{db.id}/reject", json={}).status_code == 403
    assert db.application["status"] == "pending"


def test_accepting_over_http_with_the_console_s_body(client: TestClient) -> None:
    db = _Db()
    _serve(db, _reviewer())
    body = {"notes": None, "coordinator_first_name": "Ramon", "coordinator_last_name": "Dizon"}
    response = client.post(f"/affiliates/{db.id}/accept", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["sign_in_address"] == MADE


def test_declining_is_audited_once(client: TestClient) -> None:
    db = _Db()
    _serve(db, _reviewer())
    body = {"notes": "Not registered"}
    assert client.post(f"/affiliates/{db.id}/reject", json=body).status_code == 200
    assert client.post(f"/affiliates/{db.id}/reject", json=body).status_code == 404
    assert db.audit == ["affiliate.decline"]


def test_an_unknown_status_is_refused_before_the_database(client: TestClient) -> None:
    _serve(_Db(), _reviewer())
    assert client.get("/affiliates?status=nonsense").status_code == 422


class _Form:
    def __init__(self, *, this_hour: int = 0) -> None:
        self.this_hour = this_hour
        self.saved: tuple[Any, ...] | None = None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.this_hour if "count(*)" in query else False

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        self.saved = args
        now = datetime.now(UTC)
        return {
            "id": uuid4(), "organization_name": args[0], "agency_type": args[1],
            "requested_by": None, "contact_name": args[7], "contact_email": args[2],
            "contact_phone": args[3], "address": args[4], "message": args[5],
            "status": "pending", "organization_id": None, "reviewed_by": None,
            "reviewed_at": None, "review_notes": None, "details": args[6],
            "created_at": now, "updated_at": now,
        }


_FORM = {
    "organization_name": " Hercules \n Fire Brigade ",
    "agency_type": "fire_volunteer",
    "contact_email": CONTACT,
    "contact_first_name": "Ramon",
    "contact_last_name": "Dizon",
}


def test_the_form_keeps_the_contact_person_and_one_line(client: TestClient) -> None:
    db = _Form()
    mail = _serve(db)
    response = client.post("/affiliates/register", json=_FORM)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["organization_name"] == "Hercules Fire Brigade"
    assert body["contact_name"] == "Ramon Dizon"
    assert body["details"]["contact_last_name"] == "Dizon"
    assert len(mail.sent) == 1


def test_an_older_page_without_a_name_still_applies(client: TestClient) -> None:
    _serve(_Form())
    old = {k: v for k, v in _FORM.items() if not k.startswith("contact_") or k == "contact_email"}
    response = client.post("/affiliates/register", json=old)
    assert response.status_code == 201, response.text
    assert response.json()["contact_name"] is None


def test_a_flood_is_stored_without_spending_the_mail_allowance(client: TestClient) -> None:
    db = _Form(this_hour=30)
    mail = _serve(db)
    assert client.post("/affiliates/register", json=_FORM).status_code == 201
    assert db.saved is not None and not mail.sent


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"organization_name": " \n "}, id="blank name"),
        pytest.param({"contact_email": "obryan.fircor@replit.com"}, id="made address"),
        pytest.param({"contact_first_name": "R4mon"}, id="digits in a name"),
        pytest.param({"roster": [{"full_name": "A"}] * 201}, id="roster too long"),
        pytest.param({"equipment": [{"name": "E"}] * 101}, id="equipment too long"),
    ],
)
def test_what_the_form_refuses(client: TestClient, bad: dict[str, Any]) -> None:
    db = _Form()
    mail = _serve(db)
    response = client.post("/affiliates/register", json={**_FORM, **bad})
    assert response.status_code in (400, 422), response.text
    assert db.saved is None and not mail.sent


def test_empty_optional_lines_are_none() -> None:
    form = AffiliatePublicRegister(**{**_FORM, "address": "  ", "contact_phone": ""})
    assert form.address is None and form.contact_phone is None


# --------------------------------------------------------------------------- #
# Frozen is frozen
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("standing", "admitted"), [("active", True), ("suspended", False), ("revoked", False)]
)
async def test_a_frozen_organization_gets_no_socket(
    monkeypatch: pytest.MonkeyPatch, standing: str, admitted: bool
) -> None:
    uid = uuid4()

    async def claims(*_: Any) -> dict[str, str]:
        return {"sub": str(uid)}

    async def row(query: str, *_: Any) -> dict[str, Any]:
        assert "org_standing" in query
        return {
            "id": uid, "role": "sub_admin", "agency_type": "fire_volunteer",
            "is_active": True, "org_standing": standing,
        }

    monkeypatch.setattr(ws, "decode_access_token", claims)
    monkeypatch.setattr(ws, "database", SimpleNamespace(fetchrow=row))
    socket = SimpleNamespace(
        query_params={"token": "a-token"},
        headers={},
        app=SimpleNamespace(state=SimpleNamespace(http_client=None)),
    )
    user = await ws.authenticate_websocket(socket)  # type: ignore[arg-type]
    assert (user is not None) is admitted


class _Socket:
    def __init__(self) -> None:
        self.closed: int | None = None
        self.got: list[Any] = []

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = code

    async def send_json(self, message: Any) -> None:
        self.got.append(message)


async def test_freezing_drops_that_organization_s_open_sockets_only() -> None:
    frozen, other = uuid4(), uuid4()
    live = ConnectionManager()
    theirs, others = _Socket(), _Socket()
    for socket, org in ((theirs, frozen), (others, other)):
        user = AuthenticatedUser(id=uuid4(), role="sub_admin", primary_org_id=org)
        live.subscribe(live.connect(socket, user), "map")  # type: ignore[arg-type]

    assert await live.close_organization(frozen) == 1
    await live.broadcast("map", {"type": "x"})

    assert theirs.closed == 1008 and not theirs.got
    assert others.closed is None and others.got


@pytest.mark.parametrize(("to", "drops"), [("suspended", 1), ("revoked", 1), ("active", 0)])
async def test_a_change_of_standing_drops_them(
    monkeypatch: pytest.MonkeyPatch, to: str, drops: int
) -> None:
    dropped: list[UUID] = []
    org = uuid4()

    class _Conn:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[_Conn]:
            yield self

        @asynccontextmanager
        async def transaction(self) -> AsyncIterator[None]:
            yield

        async def execute(self, *_: Any) -> str:
            return "UPDATE 1"

    async def locked(*_: Any) -> dict[str, Any]:
        return {
            "id": org, "name": "X", "standing": "active" if drops else "suspended",
            "standing_changed_at": None, "is_central_hub": False,
        }

    async def nothing(*_: Any, **__: Any) -> None:
        return None

    async def drop(org_id: UUID) -> int:
        dropped.append(org_id)
        return 1

    monkeypatch.setattr(affiliate_standing, "_locked", locked)
    monkeypatch.setattr(affiliate_standing, "record_audit", nothing)
    monkeypatch.setattr(affiliate_standing, "_summary", nothing)
    monkeypatch.setattr(affiliate_standing.manager, "close_organization", drop)
    await affiliate_standing._set_standing(
        _Conn(),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        _reviewer(),
        org,
        to=to,
        reason=None,
        note=None,
        allowed_from=("active", "suspended"),
    )
    assert len(dropped) == drops


async def test_an_organization_never_goes_with_someone_still_in_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nobody is left without the organization their access is decided by.
    org = uuid4()
    ran: list[str] = []

    class _Left:
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[_Left]:
            yield self

        @asynccontextmanager
        async def transaction(self) -> AsyncIterator[None]:
            yield

        async def fetch(self, *_: Any) -> list[dict[str, Any]]:
            return []

        async def fetchval(self, query: str, *_: Any) -> Any:
            return True if "select exists" in query else 0

        async def execute(self, query: str, *_: Any) -> str:
            ran.append(query)
            return "DELETE 1"

    async def locked(*_: Any) -> dict[str, Any]:
        return {"id": org, "name": "X", "standing": "revoked", "is_central_hub": False}

    monkeypatch.setattr(affiliate_standing, "_locked", locked)
    with pytest.raises(ConflictError):
        await affiliate_standing.delete_organization(
            org,
            OrganizationDelete(reason="duplicate", confirm_name="X"),
            None,  # type: ignore[arg-type]
            _reviewer(),
            _Left(),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    assert not ran


class _Capture:
    """Every query an alert asks, answering nobody."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def fetch(self, query: str, *_: Any) -> list[Any]:
        self.queries.append(query)
        return []

    async def fetchrow(self, query: str, *_: Any) -> dict[str, Any]:
        self.queries.append(query)
        return {"asked": ["fire_volunteer"], "designation": "Near Sample St"}

    async def fetchval(self, query: str, *_: Any) -> None:
        self.queries.append(query)


async def test_no_alert_picks_a_frozen_organization_s_people() -> None:
    area, person, org = uuid4(), uuid4(), uuid4()

    async def asked(call: Any) -> str:
        db = _Capture()
        await call(db)
        return "\n".join(db.queries)

    picked = [
        await asked(lambda db: incident_notify.notify_staff_new_incident(db, area)),
        await asked(
            lambda db: incident_notify.notify_route_recipients(
                db, area, [("fire_volunteer", org)]
            )
        ),
        await asked(
            lambda db: incident_notify.notify_bfp_alarm_request(
                db, area, "second_alarm", person
            )
        ),
        await asked(lambda db: coordinator_pings.run_pings(db, None)),
        alarm_notify._STAFF_SQL,
        fire_code_notify._COORDINATORS_SQL,
        fire_code_notify._CREWS_SQL,
    ]
    for query in picked:
        assert "frozen_org.id = u.primary_org_id" in query, query
        assert "in ('suspended', 'revoked')" in query
        assert "{" not in query.replace("'{}'", ""), "an f-string that was not one"
