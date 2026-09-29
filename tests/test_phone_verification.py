"""Phone verification through Semaphore, and the gate it opens (hermetic).

Nothing here sends a text or touches a database. Semaphore is an httpx
MockTransport; the database is an in-memory fake that answers the service's SQL
and — the part that matters most — honours transaction rollback, because two of
the guarantees under test are about what survives a refusal:

- a wrong code is counted even though the request fails, or the attempt cap
  would be decorative;
- a failed send records nothing, so it neither spends the cooldown nor counts
  toward a daily cap.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database, phone_gate_applies
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.integrations.semaphore_sms import (
    SemaphoreClient,
    SemaphoreNotConfiguredError,
    SentMessage,
    _safe_body,
    mask_number,
)
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import phone_verification as pv
from app.services.phone_verification import (
    PhoneCodeCooldownError,
    PhoneCodeLimitError,
    PhoneNumberTakenError,
    check_code,
    code_mac,
    normalize_ph_mobile,
    request_code,
    to_semaphore_number,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "supabase_jwt_secret", "test-secret")
    monkeypatch.setattr(s, "semaphore_api_key", "test-key")
    monkeypatch.setattr(s, "semaphore_sender_name", "")
    monkeypatch.setattr(s, "require_citizen_phone_verification", True)
    monkeypatch.setattr(s, "phone_otp_length", 6)
    monkeypatch.setattr(s, "phone_otp_ttl_seconds", 300)
    monkeypatch.setattr(s, "phone_otp_max_attempts", 5)
    monkeypatch.setattr(s, "phone_otp_resend_cooldown_seconds", 60)
    monkeypatch.setattr(s, "phone_otp_daily_limit_per_user", 5)
    monkeypatch.setattr(s, "phone_otp_daily_limit_per_number", 5)


def _citizen(**kw: Any) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="general_user", **kw)


# --------------------------------------------------------------------------- #
# An in-memory database that honours rollback
# --------------------------------------------------------------------------- #
class _State:
    def __init__(self) -> None:
        self.sends: list[dict[str, Any]] = []
        self.verifications: dict[UUID, dict[str, Any]] = {}
        self.users: dict[UUID, dict[str, Any]] = {}


class _Conn:
    def __init__(self, db: _FakeDb) -> None:
        self.db = db

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = copy.deepcopy(self.db.state)
        try:
            yield
        except BaseException:
            self.db.state = snapshot
            raise

    @property
    def s(self) -> _State:
        return self.db.state

    async def execute(self, query: str, *args: Any) -> str:
        q = " ".join(query.split())
        if "pg_advisory_xact_lock" in q:
            return "SELECT 1"
        if q.startswith("insert into public.phone_otp_sends"):
            self.s.sends.append(
                {"user_id": args[0], "phone": args[1], "message_id": args[2],
                 "sent_at": self.db.now()}
            )
            return "INSERT 0 1"
        if q.startswith("insert into public.user_verifications"):
            user_id, _ref, meta = args[0], args[1], json.loads(args[2])
            row = self.s.verifications.get(user_id)
            if row is None:
                self.s.verifications[user_id] = {
                    "id": uuid4(), "status": "pending", "metadata": meta,
                }
            else:
                row["metadata"] = {**row["metadata"], **meta}
                if row["status"] != "verified":
                    row["status"] = "pending"
            return "INSERT 0 1"
        if "jsonb_build_object('attempts'" in q:
            self._row_by_id(args[0])["metadata"]["attempts"] = args[1]
            return "UPDATE 1"
        if "metadata - 'code_mac' - 'expires_at' - 'attempts' where id" in q:
            meta = self._row_by_id(args[0])["metadata"]
            for key in ("code_mac", "expires_at", "attempts"):
                meta.pop(key, None)
            return "UPDATE 1"
        if q.startswith("update public.users set phone"):
            self.s.users.setdefault(args[0], {"phone_verified": False})["phone"] = args[1]
            return "UPDATE 1"
        if "set status = 'verified'" in q:
            row = self._row_by_id(args[0])
            row["status"] = "verified"
            for key in ("code_mac", "expires_at", "attempts"):
                row["metadata"].pop(key, None)
            row["metadata"]["verified_phone"] = args[2]
            # What recompute_user_verification and the unique index do.
            owner = next(u for u, r in self.s.verifications.items() if r is row)
            phone = self.s.users[owner]["phone"]
            for other, u in self.s.users.items():
                if other != owner and u.get("phone_verified") and u.get("phone") == phone:
                    raise asyncpg.UniqueViolationError("users_verified_phone_unique")
            self.s.users[owner]["phone_verified"] = True
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {q[:90]}")

    async def fetchval(self, query: str, *args: Any) -> Any:
        q = " ".join(query.split())
        if "from public.users where phone = $1 and phone_verified and id <> $2" in q:
            if self.db.racing:
                return False
            phone, me = args
            return any(
                u.get("phone") == phone and u.get("phone_verified")
                for uid, u in self.s.users.items() if uid != me
            )
        if q.startswith("select max(sent_at) from public.phone_otp_sends"):
            mine = [s["sent_at"] for s in self.s.sends if s["user_id"] == args[0]]
            return max(mine) if mine else None
        raise AssertionError(f"unexpected fetchval: {q[:90]}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        key, value, since = ("user_id", args[0], args[1]) if "where user_id" in q else (
            "phone", args[0], args[1])
        return sorted(
            ({"sent_at": s["sent_at"]} for s in self.s.sends
             if s[key] == value and s["sent_at"] > since),
            key=lambda r: r["sent_at"],
        )

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        row = self.s.verifications.get(args[0])
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"], "metadata": json.dumps(row["metadata"])}

    def _row_by_id(self, row_id: Any) -> dict[str, Any]:
        return next(r for r in self.s.verifications.values() if r["id"] == row_id)


class _FakeDb:
    def __init__(self) -> None:
        self.state = _State()
        self.clock = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
        # Simulates two confirmations passing the "number taken?" check at the
        # same instant, so only the unique index can tell them apart.
        self.racing = False

    def now(self) -> datetime:
        return self.clock

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Conn]:
        yield _Conn(self)


class _Sms:
    """Records what would have been texted; can be told to fail."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.fail = False

    async def send_otp(self, *, number: str, code: str, message: str) -> SentMessage:
        if self.fail:
            raise ExternalServiceError("The SMS service refused to send the code.")
        self.sent.append({"number": number, "code": code, "message": message})
        return SentMessage(message_id=str(len(self.sent)), status="Pending", network="Globe")

    @property
    def last_code(self) -> str:
        return self.sent[-1]["code"]


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> _FakeDb:
    fake = _FakeDb()

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return fake.clock

    monkeypatch.setattr(pv, "datetime", _Clock)
    return fake


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "typed",
    ["09171234567", "0917 123 4567", "+639171234567", "639171234567",
     "9171234567", "+63 917-123-4567"],
)
def test_the_ways_people_write_a_ph_mobile_all_normalise(typed: str) -> None:
    assert normalize_ph_mobile(typed) == "+639171234567"


@pytest.mark.parametrize(
    "typed", ["028123456", "+14155552671", "0817123456", "1234", "", "+6391712345678"]
)
def test_numbers_semaphore_could_never_reach_are_refused(typed: str) -> None:
    with pytest.raises(BadRequestError):
        normalize_ph_mobile(typed)


def test_semaphore_gets_the_number_without_the_plus() -> None:
    assert to_semaphore_number("+639171234567") == "639171234567"


def test_a_code_is_bound_to_its_account_and_number() -> None:
    a, b = uuid4(), uuid4()
    base = code_mac(a, "+639171234567", "123456")
    assert base == code_mac(a, "+639171234567", "123456")
    assert base != code_mac(b, "+639171234567", "123456")
    assert base != code_mac(a, "+639181234567", "123456")
    assert base != code_mac(a, "+639171234567", "123457")


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
async def test_a_code_is_texted_and_only_its_mac_is_kept(db: _FakeDb) -> None:
    sms, user = _Sms(), _citizen()
    out = await request_code(db, sms, user, "0917 123 4567")  # type: ignore[arg-type]

    assert out.sent and out.phone == "+639171234567"
    assert sms.sent[0]["number"] == "639171234567"
    assert len(sms.last_code) == 6 and sms.last_code.isdigit()
    assert "{otp}" in sms.sent[0]["message"]
    meta = db.state.verifications[user.id]["metadata"]
    assert set(meta) == {"phone", "code_mac", "expires_at", "attempts"}
    assert sms.last_code not in meta.values(), "the code itself must never be stored"
    assert meta["code_mac"] == code_mac(user.id, "+639171234567", sms.last_code)


async def test_asking_again_inside_the_cooldown_is_refused(db: _FakeDb) -> None:
    sms, user = _Sms(), _citizen()
    await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    db.clock += timedelta(seconds=30)
    with pytest.raises(PhoneCodeCooldownError) as err:
        await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    assert err.value.details == {"retry_after_seconds": 31}
    assert len(sms.sent) == 1

    db.clock += timedelta(seconds=31)
    await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    assert len(sms.sent) == 2


async def test_one_account_gets_five_codes_a_day(db: _FakeDb) -> None:
    sms, user = _Sms(), _citizen()
    for _ in range(5):
        await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
        db.clock += timedelta(minutes=2)
    with pytest.raises(PhoneCodeLimitError) as err:
        await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    assert (err.value.details or {})["scope"] == "account"


async def test_new_accounts_do_not_buy_more_texts_to_one_number(db: _FakeDb) -> None:
    """The per-number cap counts across accounts: a victim's phone stays quiet."""
    sms = _Sms()
    for _ in range(5):
        await request_code(db, sms, _citizen(), "09171234567")  # type: ignore[arg-type]
    with pytest.raises(PhoneCodeLimitError) as err:
        await request_code(db, sms, _citizen(), "09171234567")  # type: ignore[arg-type]
    assert (err.value.details or {})["scope"] == "number"
    assert len(sms.sent) == 5


async def test_a_failed_send_spends_nothing(db: _FakeDb) -> None:
    sms, user = _Sms(), _citizen()
    sms.fail = True
    with pytest.raises(ExternalServiceError):
        await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    assert db.state.sends == [] and user.id not in db.state.verifications

    sms.fail = False  # no cooldown to wait out: the failure was not counted
    assert (await request_code(db, sms, user, "09171234567")).sent  # type: ignore[arg-type]


async def test_a_number_verified_elsewhere_cannot_be_claimed(db: _FakeDb) -> None:
    owner = uuid4()
    db.state.users[owner] = {"phone": "+639171234567", "phone_verified": True}
    sms = _Sms()
    with pytest.raises(PhoneNumberTakenError):
        await request_code(db, sms, _citizen(), "09171234567")  # type: ignore[arg-type]
    assert sms.sent == [], "no credit spent on a number that cannot be verified"


# --------------------------------------------------------------------------- #
# Checking
# --------------------------------------------------------------------------- #
async def _sent(db: _FakeDb, user: AuthenticatedUser) -> _Sms:
    sms = _Sms()
    await request_code(db, sms, user, "09171234567")  # type: ignore[arg-type]
    db.state.users.setdefault(user.id, {"phone_verified": False})
    return sms


async def test_the_right_code_verifies_the_number(db: _FakeDb) -> None:
    user = _citizen()
    sms = await _sent(db, user)
    out = await check_code(db, user, sms.last_code)  # type: ignore[arg-type]
    assert out.verified
    assert db.state.users[user.id] == {"phone": "+639171234567", "phone_verified": True}
    assert db.state.verifications[user.id]["status"] == "verified"
    assert "code_mac" not in db.state.verifications[user.id]["metadata"]


async def test_a_wrong_code_is_counted_even_though_it_is_refused(db: _FakeDb) -> None:
    """Raising inside the transaction would roll the count back; it must not."""
    user = _citizen()
    await _sent(db, user)
    with pytest.raises(BadRequestError) as err:
        await check_code(db, user, "000000")  # type: ignore[arg-type]
    assert (err.value.details or {})["attempts_left"] == 4
    assert db.state.verifications[user.id]["metadata"]["attempts"] == 1


async def test_five_wrong_codes_throw_the_code_away(db: _FakeDb) -> None:
    user = _citizen()
    sms = await _sent(db, user)
    right = sms.last_code
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(BadRequestError):
            await check_code(db, user, wrong)  # type: ignore[arg-type]
    # Even the right code no longer works: guessing cannot continue.
    with pytest.raises(BadRequestError):
        await check_code(db, user, right)  # type: ignore[arg-type]
    assert db.state.users[user.id].get("phone_verified") is False


async def test_an_expired_code_is_refused_and_discarded(db: _FakeDb) -> None:
    user = _citizen()
    sms = await _sent(db, user)
    db.clock += timedelta(minutes=5, seconds=1)
    with pytest.raises(BadRequestError) as err:
        await check_code(db, user, sms.last_code)  # type: ignore[arg-type]
    assert (err.value.details or {})["reason"] == "expired"
    assert "code_mac" not in db.state.verifications[user.id]["metadata"]


async def test_one_accounts_code_does_not_verify_another(
    db: _FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(pv, "_generate_code", lambda _n: next(codes))
    alice, bob = _citizen(), _citizen()
    sms = await _sent(db, alice)
    db.clock += timedelta(minutes=2)
    await _sent(db, bob)
    with pytest.raises(BadRequestError):
        await check_code(db, bob, sms.sent[0]["code"])  # type: ignore[arg-type]


async def test_a_number_verified_in_the_meantime_is_refused(db: _FakeDb) -> None:
    """Both got codes before either confirmed; the second to confirm is told why."""
    alice, bob = _citizen(), _citizen()
    a = await _sent(db, alice)
    db.clock += timedelta(minutes=2)
    b = await _sent(db, bob)
    await check_code(db, alice, a.last_code)  # type: ignore[arg-type]
    with pytest.raises(PhoneNumberTakenError):
        await check_code(db, bob, b.last_code)  # type: ignore[arg-type]
    assert db.state.users[bob.id].get("phone_verified") is False


async def test_a_simultaneous_race_is_settled_by_the_index_cleanly(db: _FakeDb) -> None:
    """Both pass the check at once; the index refuses one, and nothing half-applies."""
    alice, bob = _citizen(), _citizen()
    a = await _sent(db, alice)
    db.clock += timedelta(minutes=2)
    b = await _sent(db, bob)
    await check_code(db, alice, a.last_code)  # type: ignore[arg-type]
    db.racing = True
    with pytest.raises(PhoneNumberTakenError):
        await check_code(db, bob, b.last_code)  # type: ignore[arg-type]
    # The savepoint rolled back the phone write along with the failed status change.
    assert db.state.users[bob.id] == {"phone_verified": False}
    assert db.state.verifications[bob.id]["status"] == "pending"


async def test_checking_without_asking_first_says_so(db: _FakeDb) -> None:
    with pytest.raises(BadRequestError):
        await check_code(db, _citizen(), "123456")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The Semaphore client
# --------------------------------------------------------------------------- #
def _client(handler: Any) -> SemaphoreClient:
    return SemaphoreClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


_OK_REPLY = {"message_id": 12345, "recipient": "639171234567", "code": 482913,
             "status": "Pending", "network": "Globe"}


async def test_the_client_posts_what_semaphore_documents() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["form"] = dict(x.split("=", 1) for x in req.content.decode().split("&"))
        return httpx.Response(200, json=_OK_REPLY)

    out = await _client(handler).send_otp(
        number="639171234567", code="482913", message="Code {otp}"
    )
    assert seen["url"] == "https://api.semaphore.co/api/v4/otp"
    assert seen["form"]["number"] == "639171234567"
    assert seen["form"]["code"] == "482913"
    assert seen["form"]["apikey"] == "test-key"
    assert "sendername" not in seen["form"], "empty sender means the account default"
    assert out.message_id == "12345" and out.network == "Globe"


@pytest.mark.parametrize("reply", [[_OK_REPLY], _OK_REPLY])
async def test_the_client_accepts_an_object_or_a_list(reply: Any) -> None:
    out = await _client(lambda _r: httpx.Response(200, json=reply)).send_otp(
        number="639171234567", code="1", message="{otp}"
    )
    assert out.message_id == "12345"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"apikey": ["Invalid key"]}),
        httpx.Response(200, json={"number": ["The number format is invalid."]}),
        httpx.Response(200, json=[{**_OK_REPLY, "status": "Failed"}]),
        httpx.Response(200, text="<html>maintenance</html>"),
    ],
)
async def test_a_refusal_never_reads_as_sent(response: httpx.Response) -> None:
    with pytest.raises(ExternalServiceError):
        await _client(lambda _r: response).send_otp(
            number="639171234567", code="1", message="{otp}"
        )


@pytest.mark.parametrize(
    "response",
    [
        # What Semaphore actually answered before the account had a Sender Name.
        httpx.Response(
            500,
            json=[{"senderName": "No active sender name found. Please apply for a "
                   "sender name before sending messages."}],
        ),
        httpx.Response(200, json={"sendername": ["The selected sendername is invalid."]}),
    ],
)
async def test_no_approved_sender_name_is_a_setup_problem_not_a_retry(
    response: httpx.Response,
) -> None:
    """The app says texts are unavailable, not "try again in a minute"."""
    with pytest.raises(SemaphoreNotConfiguredError):
        await _client(lambda _r: response).send_otp(
            number="639171234567", code="1", message="{otp}"
        )


async def test_no_api_key_is_a_clear_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "semaphore_api_key", "")
    with pytest.raises(SemaphoreNotConfiguredError):
        await _client(lambda _r: httpx.Response(200, json=_OK_REPLY)).send_otp(
            number="639171234567", code="1", message="{otp}"
        )


async def test_a_lost_connection_is_retried_but_a_lost_reply_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry after the request may have landed would text — and bill — twice."""

    async def _no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(SemaphoreClient._post_otp.retry, "sleep", _no_wait)
    calls = {"connect": 0, "read": 0}

    def flaky_connect(_r: httpx.Request) -> httpx.Response:
        calls["connect"] += 1
        if calls["connect"] < 3:
            raise httpx.ConnectError("no route")
        return httpx.Response(200, json=_OK_REPLY)

    await _client(flaky_connect).send_otp(number="639171234567", code="1", message="{otp}")
    assert calls["connect"] == 3

    def slow_reply(_r: httpx.Request) -> httpx.Response:
        calls["read"] += 1
        raise httpx.ReadTimeout("no reply")

    with pytest.raises(ExternalServiceError):
        await _client(slow_reply).send_otp(number="639171234567", code="1", message="{otp}")
    assert calls["read"] == 1


def test_logs_never_carry_the_code_or_the_whole_number() -> None:
    body = _safe_body(httpx.Response(200, json=[{**_OK_REPLY, "message": "Code 482913"}]))
    assert "482913" not in body
    assert mask_number("+639171234567") == "***567"


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def test_only_an_unverified_citizen_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    assert phone_gate_applies(_citizen())
    assert not phone_gate_applies(_citizen(phone_verified=True))
    for role in ("admin", "sub_admin", "response_team"):
        assert not phone_gate_applies(AuthenticatedUser(id=uuid4(), role=role))
    monkeypatch.setattr(get_settings(), "require_citizen_phone_verification", False)
    assert not phone_gate_applies(_citizen())


class _AreasDb:
    async def fetch(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_an_unverified_citizen_is_refused_with_its_own_error_code(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: _citizen()
    app.dependency_overrides[get_database] = lambda: _AreasDb()
    response = client.get("/areas")
    assert response.status_code == 403
    assert response.json()["error"] == "phone_not_verified"


def test_an_unverified_citizen_can_still_reach_what_verifying_needs(client: TestClient) -> None:
    user = _citizen()
    app.dependency_overrides[get_current_user] = lambda: user
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["phone_verified"] is False
    assert me.json()["phone_verification_required"] is True, "the app's cue to show the gate"


def test_the_kill_switch_reaches_the_app(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "require_citizen_phone_verification", False)
    app.dependency_overrides[get_current_user] = lambda: _citizen()
    assert client.get("/auth/me").json()["phone_verification_required"] is False


def test_a_verified_citizen_is_let_through(client: TestClient) -> None:
    app.dependency_overrides[get_current_user] = lambda: _citizen(phone_verified=True)
    app.dependency_overrides[get_database] = lambda: _AreasDb()
    assert client.get("/areas").status_code == 200
