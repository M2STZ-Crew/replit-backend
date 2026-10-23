"""One Admin console, an Admin per organisation (ARBAC; hermetic).

What these pin (PRD v13/v14 §4.6; REPLIT (MAIN) pass 6, A00 "Four permission
variants"):
- every organisation's Admin sees every incident but acknowledges only the
  ones its agency was asked for (Fire Volunteer and BFP for Fire), and records
  the acknowledgement under its organisation's agency and team;
- it never rejects, marks fire out or dispatches: those stay Coordinators';
- the central hub (Barangay 76) also reviews affiliates and IDs, and nothing
  more — it is not a superuser; the Admin with no organisation is the system
  account and keeps everything it had;
- a Fire Volunteer Admin asks BFP to raise the alarm, the BFP Admin decides;
- an Admin reads its own organisation's people, its routed incidents' audit
  entries and its own people's, and creates its own Coordinators;
- GET /auth/me tells the console all of this, and nothing else leaks.

Routes are called directly against small in-memory fakes.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.api import deps
from app.api.routes import (
    alarm_requests,
    audit,
    auth,
    equipment,
    incidents,
    org_accounts,
    organizations,
    post_incident_reports,
)
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.schemas.alarm import AlarmReviewRequest
from app.schemas.auth import AuthenticatedUser
from app.schemas.organization import CoordinatorCreateRequest
from app.services import access as A
from app.services.incident import assert_coordinator, assert_transition, is_coordinator

AREA = uuid4()
OWN_ORG = uuid4()
OTHER_ORG = uuid4()


def _admin(
    agency: str | None = None,
    *,
    hub: bool = False,
    active: bool = True,
    org: UUID = OWN_ORG,
    name: str = "PNP Pasay",
) -> AuthenticatedUser:
    """An Admin of an organisation of ``agency``; with no agency, the system Admin."""
    if agency is None:
        return AuthenticatedUser(id=uuid4(), role="admin", full_name="System Administrator")
    return AuthenticatedUser(
        id=uuid4(),
        role="admin",
        full_name=f"{name} Admin",
        primary_org_id=org,
        org_name=name,
        org_agency_type=agency,
        org_is_active=active,
        org_is_central_hub=hub,
    )


# --------------------------------------------------------------------------- #
# The permission table
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("agency", "hub", "variant", "act", "extra", "absent"),
    [
        ("police", False, "police", ("police",), set(), {A.REVIEW_AFFILIATES, A.DECIDE_ALARM}),
        ("medical", False, "medical", ("medical",), set(), {A.REQUEST_ALARM, A.REVIEW_IDS}),
        ("barangay", False, "barangay", ("barangay",), set(), {A.REVIEW_AFFILIATES}),
        ("fire_volunteer", False, "fire_volunteer", A.FIRE_AGENCIES, {A.REQUEST_ALARM},
         {A.DECIDE_ALARM}),
        ("bfp", False, "bfp", A.FIRE_AGENCIES, {A.DECIDE_ALARM}, {A.REQUEST_ALARM}),
        ("barangay", True, "central", ("barangay",),
         {A.REVIEW_AFFILIATES, A.REVIEW_IDS, A.ALL_ORGANIZATIONS}, {A.DECIDE_ALARM}),
    ],
)
def test_the_four_variants(
    agency: str, hub: bool, variant: str, act: tuple[str, ...], extra: set[str], absent: set[str]
) -> None:
    access = A.admin_access(_admin(agency, hub=hub))
    assert access is not None
    assert access.variant == variant
    assert access.act_agencies == act
    every = {A.ACKNOWLEDGE, A.DECIDE_OVERLAPS, A.DELETE_WATER, A.CREATE_COORDINATORS}
    assert access.permissions == frozenset(every | extra)
    assert not access.permissions & absent
    # No organisation's Admin coordinates, manages the map, or reads everything.
    for never in (A.COORDINATE, A.MANAGE_MAP, A.MANAGE_ANY_ACCOUNT, A.ALL_RECORDS):
        assert not access.can(never)


def test_the_central_hub_is_not_a_superuser() -> None:
    hub = A.admin_access(_admin("barangay", hub=True, name="Barangay 76 Zone 10 Pasay"))
    assert hub is not None and hub.scope == "central"
    # It acknowledges what asked for Barangay, like any Barangay Admin.
    assert hub.acts_on(["barangay", "fire_volunteer"])
    assert not hub.acts_on(["fire_volunteer"])
    assert not hub.can(A.COORDINATE) and not hub.can(A.ALL_RECORDS)


def test_the_system_admin_keeps_everything() -> None:
    system = A.admin_access(_admin())
    assert system is not None and system.is_system and system.scope == "system"
    assert system.act_agencies is None and system.acts_on([])
    assert system.permissions == A._SYSTEM


def test_a_turned_off_organisation_fails_closed() -> None:
    access = A.admin_access(_admin("police", active=False))
    assert access is not None
    assert access.permissions == frozenset() and access.act_agencies == ()
    assert not access.acts_on(["police"])


def test_only_admins_have_console_access() -> None:
    for role in ("sub_admin", "response_team", "general_user"):
        staff = AuthenticatedUser(id=uuid4(), role=role, agency_type="police")
        assert A.admin_access(staff) is None


def test_an_org_admin_records_its_organisations_agency() -> None:
    assert A.acting_agency(_admin("police")) == "police"
    assert A.acting_agency(_admin()) is None
    captain = AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="bfp")
    assert A.acting_agency(captain) == "bfp"


def test_org_admins_never_coordinate() -> None:
    police = _admin("police")
    assert not is_coordinator(police)
    with pytest.raises(ForbiddenError) as exc:
        assert_coordinator(police, "reject incidents")
    assert "Coordinators do" in exc.value.message
    assert is_coordinator(_admin())


# --------------------------------------------------------------------------- #
# GET /auth/me and the loaded user
# --------------------------------------------------------------------------- #
async def test_me_tells_the_console_and_hides_the_organisation_columns() -> None:
    body = (await auth.me(_admin("police"))).model_dump(mode="json")
    assert body["console"]["variant"] == "police"
    assert body["console"]["scope"] == "organization"
    assert body["console"]["act_agencies"] == ["police"]
    assert body["console"]["organization"]["name"] == "PNP Pasay"
    assert A.ACKNOWLEDGE in body["console"]["permissions"]
    assert A.REVIEW_AFFILIATES not in body["console"]["permissions"]
    assert not {"org_name", "org_agency_type", "org_is_central_hub"} & body.keys()

    system = (await auth.me(_admin())).model_dump(mode="json")
    assert system["console"]["variant"] == "system"
    assert system["console"]["act_agencies"] is None

    citizen = AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)
    assert (await auth.me(citizen)).console is None


def test_the_hub_flag_works_before_its_migration() -> None:
    # Read through to_jsonb: a database without the column reads false.
    assert "to_jsonb(o) ->> 'is_central_hub'" in deps.CURRENT_USER_SQL
    assert "left join public.organizations o" in deps.CURRENT_USER_SQL


async def test_the_current_user_carries_its_organisation(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()

    async def _claims(_token: str, _http: Any) -> dict[str, str]:
        return {"sub": str(user_id)}

    class _Db:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            assert query == deps.CURRENT_USER_SQL
            return {
                "id": user_id, "email": "pnp.admin@replit.com", "phone": None,
                "role": "admin", "agency_type": None, "verified_percent": 0,
                "badge": "yellow", "full_name": "PNP Pasay Admin",
                "primary_org_id": OWN_ORG, "mobile": None, "date_of_birth": None,
                "gender": None, "phone_verified": False, "is_active": True,
                "org_name": "PNP Pasay", "org_agency_type": "police",
                "org_is_active": True, "org_is_central_hub": False,
            }

    monkeypatch.setattr(deps, "decode_access_token", _claims)
    request = SimpleNamespace(state=SimpleNamespace())
    creds = SimpleNamespace(credentials="token")
    user = await deps.get_current_user(request, creds, _Db(), None)  # type: ignore[arg-type]
    assert user.org_agency_type == "police" and user.org_name == "PNP Pasay"
    assert request.state.actor_agency == "police"


async def test_central_duties_are_refused_to_other_admins() -> None:
    reviewer = deps.require_admin_permission(A.REVIEW_AFFILIATES, "central hub only")
    with pytest.raises(ForbiddenError) as exc:
        await reviewer(_admin("police"))
    assert exc.value.message == "central hub only"
    assert await reviewer(_admin("barangay", hub=True)) is not None
    assert await reviewer(_admin()) is not None
    with pytest.raises(ForbiddenError):
        await reviewer(AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="police"))


# --------------------------------------------------------------------------- #
# Acknowledge
# --------------------------------------------------------------------------- #
class _IncidentDb:
    """The accept route's SQL, for one incident that asked for ``requested``."""

    def __init__(self, requested: set[str], status: str = "reported") -> None:
        self.requested = requested
        self.status = status
        self.acceptances: list[dict[str, Any]] = []
        self.audit_agencies: list[str | None] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_IncidentDb]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = (self.status, copy.deepcopy(self.acceptances))
        try:
            yield
        except BaseException:
            self.status, self.acceptances = snapshot
            raise

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        if q.startswith("select status::text from public.areas where id = $1"):
            return self.status
        if "r.selected_agencies &&" in q:
            return bool(self.requested & set(args[1]))
        if "where area_id = $1 and user_id = $2" in q:
            return any(a["user_id"] == args[1] for a in self.acceptances)
        if "where area_id = $1 and is_first" in q:
            return any(a["is_first"] for a in self.acceptances)
        raise AssertionError(f"unexpected fetchval: {q[:100]}")

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if q.startswith("update public.areas set status = 'verified'"):
            assert_transition(self.status, "verified")
            self.status = "verified"
        elif q.startswith("insert into public.area_acceptances"):
            self.acceptances.append(
                {"user_id": args[1], "agency": args[2], "organization_id": args[3],
                 "is_first": args[4]}
            )
        elif q.startswith("insert into public.audit_logs"):
            self.audit_agencies.append(args[2])
        else:
            raise AssertionError(f"unexpected execute: {q[:100]}")
        return "OK"


@pytest.fixture
def finished(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _finish(_db: Any, _id: UUID, event_type: str) -> str:
        seen.append(event_type)
        return event_type

    monkeypatch.setattr(incidents, "finish_incident_change", _finish)
    return seen


async def _acknowledge(db: _IncidentDb, user: AuthenticatedUser) -> Any:
    return await incidents.accept_incident(AREA, None, user, db)  # type: ignore[arg-type]


async def test_police_acknowledges_what_asked_for_police(finished: list[str]) -> None:
    db = _IncidentDb({"fire_volunteer", "police"})
    police = _admin("police")
    await _acknowledge(db, police)
    assert db.status == "verified"
    assert db.acceptances == [
        {"user_id": police.id, "agency": "police", "organization_id": OWN_ORG, "is_first": True}
    ]
    assert db.audit_agencies == ["police"]
    assert finished == ["incident_verified"]


async def test_police_only_follows_a_fire_it_was_not_asked_for(finished: list[str]) -> None:
    db = _IncidentDb({"fire_volunteer", "medical"})
    with pytest.raises(ForbiddenError) as exc:
        await _acknowledge(db, _admin("police"))
    assert exc.value.details["access"] == "view_only"
    assert "didn't ask for Police" in exc.value.message
    assert db.status == "reported" and db.acceptances == []
    assert finished == []


async def test_fire_admins_answer_each_others_fires(finished: list[str]) -> None:
    db = _IncidentDb({"bfp"})
    await _acknowledge(db, _admin("fire_volunteer", name="Hercules Fire Brigade"))
    assert db.acceptances[0]["agency"] == "fire_volunteer"


async def test_a_later_admin_adds_its_organisation(finished: list[str]) -> None:
    db = _IncidentDb({"fire_volunteer", "police"}, status="verified")
    db.acceptances.append(
        {"user_id": uuid4(), "agency": "fire_volunteer", "organization_id": OTHER_ORG,
         "is_first": True}
    )
    await _acknowledge(db, _admin("police"))
    assert db.status == "verified"
    assert db.acceptances[-1]["is_first"] is False
    assert db.acceptances[-1]["agency"] == "police"
    assert finished == ["incident_accepted"]


async def test_the_system_admin_acknowledges_anything(finished: list[str]) -> None:
    db = _IncidentDb({"medical"})
    await _acknowledge(db, _admin())
    assert db.acceptances[0]["agency"] is None
    assert db.acceptances[0]["organization_id"] is None


async def test_a_turned_off_organisation_cannot_acknowledge(finished: list[str]) -> None:
    db = _IncidentDb({"police"})
    with pytest.raises(ForbiddenError):
        await _acknowledge(db, _admin("police", active=False))
    assert db.acceptances == []


async def test_reporters_are_kept_from_admins_not_asked() -> None:
    db = _IncidentDb({"fire_volunteer"})
    with pytest.raises(ForbiddenError):
        await incidents.list_incident_reports(AREA, _admin("police"), db, None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Alarm escalation
# --------------------------------------------------------------------------- #
def test_fire_volunteers_ask_and_bfp_decides() -> None:
    assert alarm_requests._may_request(_admin("fire_volunteer"))
    assert not alarm_requests._may_request(_admin("bfp"))
    assert not alarm_requests._may_request(_admin("police"))
    assert alarm_requests._may_decide(_admin("bfp"))
    assert not alarm_requests._may_decide(_admin("fire_volunteer"))
    assert not alarm_requests._may_decide(_admin())
    assert alarm_requests._may_decide(
        AuthenticatedUser(id=uuid4(), role="sub_admin", agency_type="bfp")
    )


async def test_the_bfp_admin_is_told_plainly_before_the_migration() -> None:
    class _Db:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            return {"area_id": AREA, "lvl": "second_alarm", "status": "pending"}

        async def execute(self, query: str, *args: Any) -> str:
            raise asyncpg.InsufficientPrivilegeError("only BFP sub-admins may set alarm levels")

    with pytest.raises(ForbiddenError) as exc:
        await alarm_requests.execute_alarm_request(
            uuid4(), AlarmReviewRequest(), _admin("bfp", name="BFP Pasay"), _Db()  # type: ignore[arg-type]
        )
    assert "BFP Coordinator can set it" in exc.value.message


# --------------------------------------------------------------------------- #
# Records and people
# --------------------------------------------------------------------------- #
class _Capture:
    """Records the one listing query a route makes, and answers it with ``rows``."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.query = ""
        self.args: tuple[Any, ...] = ()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.query, self.args = " ".join(query.split()), args
        return self.rows

    async def fetchval(self, query: str, *args: Any) -> Any:
        return 1


def _audit_row(**over: Any) -> dict[str, Any]:
    row = {
        "id": uuid4(), "actor_user_id": uuid4(), "actor_role": "sub_admin",
        "actor_agency": "police", "actor_name": "Rowena Pascual",
        "actor_organization": "PNP Pasay", "action": "incident.verify",
        "entity_type": "area", "entity_id": AREA, "area_id": AREA,
        "before_state": None, "after_state": None, "metadata": "{}",
        "ip_address": "203.0.113.9", "user_agent": "phone", "request_id": "r1",
        "created_at": datetime.now(UTC), "area_designation": "Area 1",
    }
    row.update(over)
    return row


async def _audit(db: _Capture, user: AuthenticatedUser) -> list[Any]:
    return await audit.list_audit_logs(
        user, db, action=None, entity_type=None, area_id=None,  # type: ignore[arg-type]
        actor_user_id=None, limit=100, offset=0,
    )


async def test_an_org_admins_audit_log_is_its_incidents_and_its_people() -> None:
    db = _Capture([_audit_row()])
    rows = await _audit(db, _admin("police"))
    assert "r.selected_agencies && $1::public.agency_type[]" in db.query
    assert "au.primary_org_id = $2" in db.query
    assert db.args[:2] == (["police"], OWN_ORG)
    assert rows[0].ip_address is None and rows[0].user_agent is None
    assert rows[0].actor_name == "Rowena Pascual"


async def test_the_system_admin_reads_the_whole_audit_log() -> None:
    db = _Capture([_audit_row()])
    rows = await _audit(db, _admin())
    assert "selected_agencies" not in db.query
    assert "au.primary_org_id = $" not in db.query
    assert rows[0].ip_address == "203.0.113.9"


async def test_org_admins_read_reports_of_incidents_they_took_part_in() -> None:
    db = _Capture()
    await post_incident_reports.list_post_incident_reports(
        _admin("medical"), db, area_id=None, limit=50, offset=0  # type: ignore[arg-type]
    )
    assert "x.organization_id = $1" in db.query
    assert "d.organization_id = $1" in db.query
    assert db.args[0] == OWN_ORG

    system = _Capture()
    await post_incident_reports.list_post_incident_reports(
        _admin(), system, area_id=None, limit=50, offset=0  # type: ignore[arg-type]
    )
    assert "organization_id = $" not in system.query


async def test_an_org_admin_reads_its_own_people_only() -> None:
    with pytest.raises(ForbiddenError):
        await organizations.list_org_personnel(OTHER_ORG, _admin("police"), _Capture())  # type: ignore[arg-type]
    db = _Capture()
    await organizations.list_org_personnel(OWN_ORG, _admin("police"), db)  # type: ignore[arg-type]
    assert "rr.title" in db.query and "u.email" in db.query
    # The hub reviews affiliates, so it opens any organisation's people.
    await organizations.list_org_personnel(
        OTHER_ORG, _admin("barangay", hub=True), _Capture()  # type: ignore[arg-type]
    )


def test_equipment_follows_the_same_rule() -> None:
    police, hub = _admin("police"), _admin("barangay", hub=True)
    assert equipment._can_view_org(police, OWN_ORG)
    assert not equipment._can_view_org(police, OTHER_ORG)
    assert equipment._can_view_org(hub, OTHER_ORG)
    assert not equipment._can_manage_org(hub, OTHER_ORG)
    assert equipment._can_manage_org(_admin(), OTHER_ORG)


# --------------------------------------------------------------------------- #
# Coordinator accounts
# --------------------------------------------------------------------------- #
class _Auth:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.new_id = str(uuid4())

    async def admin_create_user(self, **kw: Any) -> dict[str, Any]:
        self.created.append(kw["email"])
        return {"id": self.new_id}

    async def admin_generate_link(self, **kw: Any) -> dict[str, Any]:
        return {"action_link": "https://example.test/set-password"}

    async def admin_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)


class _Email:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    async def send(self, *, to: str, subject: str, html: str, text: str | None = None) -> None:
        from app.core.exceptions import AppError

        if self.fail:
            raise AppError("smtp down")
        self.sent.append(to)


class _AccountsDb:
    def __init__(self, *, taken: bool = False, org_agency: str = "police") -> None:
        self.taken = taken
        self.org_agency = org_agency
        self.profile: dict[str, Any] = {}
        self.roster: list[tuple[Any, ...]] = []
        self.audits: list[str] = []

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_AccountsDb]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = " ".join(query.split())
        if "from public.organizations where id = $1" in q:
            return {"id": args[0], "name": "PNP Pasay", "agency_type": self.org_agency,
                    "is_active": True}
        if "where u.id = $1" in q:
            return {
                "id": args[0], "full_name": self.profile.get("full_name"), "role": "sub_admin",
                "agency_type": self.profile.get("agency"), "verified_percent": 0,
                "badge": "yellow", "email": "d.villareal@pnp.example", "title": "Lieutenant",
                "is_active": True, "created_at": datetime.now(UTC),
                "created_by_name": "PNP Pasay Admin", "deactivated_at": None,
            }
        raise AssertionError(f"unexpected fetchrow: {q[:100]}")

    async def fetchval(self, query: str, *args: Any) -> Any:
        return 1 if self.taken else None

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if q.startswith("update public.users set role = 'sub_admin'"):
            self.profile = {"id": args[0], "agency": args[1], "org": args[2],
                            "full_name": args[3], "created_by": args[4]}
            return "UPDATE 1"
        if q.startswith("insert into public.org_roster"):
            self.roster.append(args)
            return "INSERT 0 1"
        if q.startswith("insert into public.audit_logs"):
            self.audits.append(args[3])
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {q[:100]}")


def _new_coordinator(org: UUID | None = None) -> CoordinatorCreateRequest:
    return CoordinatorCreateRequest(
        full_name="Dante Villareal", email="D.Villareal@pnp.example", title="Lieutenant",
        organization_id=org,
    )


async def _create(
    db: _AccountsDb, admin: AuthenticatedUser, body: CoordinatorCreateRequest,
    auth_client: _Auth | None = None, email: _Email | None = None,
) -> Any:
    return await org_accounts.create_coordinator(
        body, None, admin, db, auth_client or _Auth(), email or _Email()  # type: ignore[arg-type]
    )


async def test_an_admin_creates_its_own_coordinator() -> None:
    db, auth_client, email = _AccountsDb(), _Auth(), _Email()
    police = _admin("police")
    result = await _create(db, police, _new_coordinator(), auth_client, email)
    assert auth_client.created == ["d.villareal@pnp.example"]
    assert db.profile["agency"] == "police" and db.profile["org"] == OWN_ORG
    assert db.profile["created_by"] == police.id
    assert db.roster[0][2] == "Lieutenant"
    assert db.audits == ["user.coordinator_created"]
    assert email.sent == ["d.villareal@pnp.example"]
    assert result.invite_email_sent and result.coordinator.title == "Lieutenant"


async def test_an_admin_cannot_create_into_another_organisation() -> None:
    db, auth_client = _AccountsDb(), _Auth()
    with pytest.raises(ForbiddenError):
        await _create(db, _admin("police"), _new_coordinator(OTHER_ORG), auth_client)
    assert auth_client.created == []


async def test_the_system_admin_names_the_organisation() -> None:
    with pytest.raises(BadRequestError):
        await _create(_AccountsDb(), _admin(), _new_coordinator())
    result = await _create(_AccountsDb(), _admin(), _new_coordinator(OTHER_ORG))
    assert result.coordinator.role == "sub_admin"


async def test_an_email_in_use_is_not_taken_over() -> None:
    auth_client = _Auth()
    with pytest.raises(ConflictError):
        await _create(_AccountsDb(taken=True), _admin("police"), _new_coordinator(), auth_client)
    assert auth_client.created == []


async def test_a_failed_email_still_leaves_a_working_account() -> None:
    result = await _create(
        _AccountsDb(), _admin("police"), _new_coordinator(), email=_Email(fail=True)
    )
    assert not result.invite_email_sent
    assert "Forgot password" in (result.detail or "")


async def test_another_organisations_coordinator_is_not_found() -> None:
    class _Db:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
            return {"role": "sub_admin", "primary_org_id": OTHER_ORG}

    with pytest.raises(NotFoundError):
        await org_accounts.deactivate_coordinator(
            uuid4(), None, _admin("police"), _Db(), _Auth()  # type: ignore[arg-type]
        )
