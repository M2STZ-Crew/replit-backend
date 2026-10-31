"""National ID review with PSA's PhilSys Check (hermetic).

What these pin:
- A submission carries the QR photo and the holder's consent, or nothing is kept.
- Only the central hub reviews, and approving needs PhilSys Check's "Verified".
- The photos are deleted before a decision is recorded, on both outcomes.
- A failed check is recorded, the resident is told why, and a push that fails
  does not fail the decision.

The SQL these fakes cannot run was exercised on a real Postgres; see CHANGELOG.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user, get_database, get_storage_client
from app.api.routes import admin as admin_routes
from app.core.exceptions import ExternalServiceError
from app.integrations.supabase_storage import SupabaseStorageClient
from app.main import app
from app.schemas.admin import VerificationApproveRequest, VerificationReviewRequest
from app.schemas.auth import AuthenticatedUser
from app.services import national_id

_ORG = uuid4()
_VERIFIED = {"philsys_result": "verified"}
_JPEG = ("photo.jpg", b"jpeg bytes", "image/jpeg")


def _hub_admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name="Hub Admin", primary_org_id=_ORG, org_name="Hub",
        org_agency_type="barangay", org_is_active=True, org_is_central_hub=True,
    )


def _other_admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(), role="admin", full_name="BFP Admin", primary_org_id=_ORG, org_name="BFP",
        org_agency_type="bfp", org_is_active=True,
    )


def _citizen() -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role="general_user", phone_verified=True)


class _Storage:
    """Records what reached Storage; ``failing`` makes the named call raise."""

    def __init__(self, failing: str | None = None) -> None:
        self.uploaded: list[tuple[str, str, str]] = []
        self.removed: list[tuple[str, str]] = []
        self.failing = failing

    async def upload(self, *, bucket: str, path: str, content: bytes, content_type: str) -> str:
        if self.failing == path.rsplit("/", 1)[-1]:
            raise ExternalServiceError("Storage rejected the upload.")
        self.uploaded.append((bucket, path, content_type))
        return path

    async def remove(self, *, bucket: str, path: str) -> None:
        if self.failing == "remove":
            raise ExternalServiceError("Storage delete error.")
        self.removed.append((bucket, path))

    async def create_signed_url(self, *, bucket: str, path: str) -> str:
        return f"https://storage.test/{path}?token=signed"


class _Db:
    """One review: pending until an update lands."""

    def __init__(self, user_id: UUID | None = None, *, pending: bool = True) -> None:
        self.user_id = user_id or uuid4()
        self.pending = pending
        self.queries: list[str] = []
        self.args: list[tuple[Any, ...]] = []
        self.calls: list[str] = []
        self.storage: _Storage | None = None

    def _note(self, query: str, args: tuple[Any, ...]) -> str:
        q = " ".join(query.split())
        self.queries.append(q)
        self.args.append(args)
        return q

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = self._note(query, args)
        if "from public.user_verifications uv" in q:
            return [{
                "id": uuid4(), "user_id": self.user_id, "email": "r@example.test",
                "full_name": "Example Resident", "type": "national_id",
                "status": "manual_review", "provider": "manual",
                "submitted_at": datetime.now(UTC), "id_path": "u/national_id",
                "selfie_path": "u/selfie", "qr_path": "u/national_id_qr",
            }]
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = self._note(query, args)
        if q.startswith("select metadata->>'id_path'"):
            if not self.pending:
                return None
            return {
                "id_path": "u/national_id", "selfie_path": "u/selfie",
                "qr_path": "u/national_id_qr",
            }
        if q.startswith("update public.user_verifications"):
            assert self.storage is None or self.storage.removed, "photos go first"
            if not self.pending:
                return None
            self.pending = False
            return {"user_id": self.user_id}
        return {"verified_percent": 50, "badge": "light_green"}

    async def execute(self, query: str, *args: Any) -> str:
        self._note(query, args)
        return "INSERT 0 1"

    def write(self, starts: str) -> tuple[Any, ...]:
        return next(a for q, a in zip(self.queries, self.args, strict=True) if q.startswith(starts))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(user: AuthenticatedUser, db: _Db, storage: _Storage) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_storage_client] = lambda: storage


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What the resident was told, in place of the inbox and the push."""
    told: list[dict[str, Any]] = []

    async def notify(_db: Any, user_id: UUID, *, approved: bool, notes: str | None = None) -> int:
        told.append({"user_id": user_id, "approved": approved, "notes": notes})
        return 1

    monkeypatch.setattr(admin_routes, "notify_review_decided", notify)
    return told


def _submit(client: TestClient, *, qr: bool = True, consent: bool = True) -> Any:
    files = {"id_image": _JPEG, "selfie_image": _JPEG}
    if qr:
        files["qr_image"] = _JPEG
    return client.post(
        "/verification/national-id/manual",
        files=files,
        data={"philsys_consent": "true"} if consent else {},
    )


# --------------------------------------------------------------------------- #
# Submitting
# --------------------------------------------------------------------------- #
def test_a_submission_keeps_three_photos_and_the_consent(client: TestClient) -> None:
    user, db, storage = _citizen(), _Db(), _Storage()
    _wire(user, db, storage)
    assert _submit(client).status_code == 200
    assert storage.uploaded == [
        ("national-ids", f"{user.id}/national_id", "image/jpeg"),
        ("national-ids", f"{user.id}/selfie", "image/jpeg"),
        ("national-ids", f"{user.id}/national_id_qr", "image/jpeg"),
    ]
    metadata = json.loads(db.write("insert into public.user_verifications")[1])
    assert metadata["qr_path"] == f"{user.id}/national_id_qr"
    assert datetime.fromisoformat(metadata["philsys_consent_at"])


def test_an_older_app_is_told_why_and_nothing_is_kept(client: TestClient) -> None:
    db, storage = _Db(), _Storage()
    _wire(_citizen(), db, storage)
    answer = _submit(client, qr=False, consent=False)
    assert answer.status_code == 400
    assert "Update RepLiT" in answer.json()["message"]
    assert storage.uploaded == [] and db.queries == []


def test_no_consent_no_upload(client: TestClient) -> None:
    db, storage = _Db(), _Storage()
    _wire(_citizen(), db, storage)
    answer = _submit(client, consent=False)
    assert answer.status_code == 400
    assert "PhilSys Check" in answer.json()["message"]
    assert storage.uploaded == [] and db.queries == []


def test_a_bad_qr_photo_stops_the_other_two_as_well(client: TestClient) -> None:
    db, storage = _Db(), _Storage()
    _wire(_citizen(), db, storage)
    answer = client.post(
        "/verification/national-id/manual",
        files={
            "id_image": _JPEG, "selfie_image": _JPEG,
            "qr_image": ("qr.gif", b"gif bytes", "image/gif"),
        },
        data={"philsys_consent": "true"},
    )
    assert answer.status_code == 400
    assert storage.uploaded == [] and db.queries == []


def test_an_upload_that_fails_halfway_leaves_nothing_behind(client: TestClient) -> None:
    user, db, storage = _citizen(), _Db(), _Storage(failing="national_id_qr")
    _wire(user, db, storage)
    assert _submit(client).status_code == 502
    assert ("national-ids", f"{user.id}/national_id") in storage.removed
    assert ("national-ids", f"{user.id}/selfie") in storage.removed
    assert db.queries == []


def test_a_new_submission_clears_the_last_review(client: TestClient) -> None:
    db = _Db()
    _wire(_citizen(), db, _Storage())
    assert _submit(client).status_code == 200
    upsert = next(q for q in db.queries if q.startswith("insert into"))
    assert "- 'philsys_result'" in upsert and "review_notes = null" in upsert


# --------------------------------------------------------------------------- #
# Reviewing
# --------------------------------------------------------------------------- #
def test_the_reviewer_gets_the_qr_photo_and_a_file_to_upload(client: TestClient) -> None:
    db, storage = _Db(), _Storage()
    _wire(_hub_admin(), db, storage)
    item = client.get("/admin/verifications/pending").json()[0]
    assert item["qr_image_url"] == "https://storage.test/u/national_id_qr?token=signed"
    assert item["qr_download_url"] == f"{item['qr_image_url']}&download=philsys-qr.jpg"


def test_a_submission_without_a_qr_photo_has_no_download(client: TestClient) -> None:
    class NoQr(_Db):
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            rows = await super().fetch(query, *args)
            return [{**r, "qr_path": None} for r in rows]

    _wire(_hub_admin(), NoQr(), _Storage())
    item = client.get("/admin/verifications/pending").json()[0]
    assert item["qr_image_url"] is None and item["qr_download_url"] is None


@pytest.mark.parametrize("user", [_other_admin(), _citizen()], ids=["other_admin", "citizen"])
def test_only_the_hub_reviews(client: TestClient, user: AuthenticatedUser) -> None:
    db, storage = _Db(), _Storage()
    _wire(user, db, storage)
    case = uuid4()
    assert client.get("/admin/verifications/pending").status_code == 403
    assert client.post(f"/admin/verifications/{case}/approve", json=_VERIFIED).status_code == 403
    assert client.post(f"/admin/verifications/{case}/reject", json={}).status_code == 403
    assert db.queries == [] and storage.removed == []


@pytest.mark.parametrize("body", [None, {}, {"philsys_result": "deactivated"}])
def test_approving_needs_philsys_checks_verified(client: TestClient, body: Any) -> None:
    db, storage = _Db(), _Storage()
    _wire(_hub_admin(), db, storage)
    answer = client.post(f"/admin/verifications/{uuid4()}/approve", json=body)
    assert answer.status_code == 422
    assert db.queries == [] and storage.removed == []


def test_approving_deletes_the_photos_first(
    client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    admin, db, storage = _hub_admin(), _Db(), _Storage()
    db.storage = storage
    _wire(admin, db, storage)
    answer = client.post(f"/admin/verifications/{uuid4()}/approve", json=_VERIFIED)
    assert answer.status_code == 200 and answer.json()["verified"] is True
    assert storage.removed == [
        ("national-ids", "u/national_id"),
        ("national-ids", "u/selfie"),
        ("national-ids", "u/national_id_qr"),
    ]
    update = next(q for q in db.queries if q.startswith("update"))
    assert "- 'id_path' - 'selfie_path' - 'qr_path'" in update
    assert db.write("update")[3] == "verified"
    assert pushes == [{"user_id": db.user_id, "approved": True, "notes": None}]


def test_rejecting_deletes_the_photos_and_records_the_failed_check(
    client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    admin, db, storage = _hub_admin(), _Db(), _Storage()
    db.storage = storage
    _wire(admin, db, storage)
    reason = "PhilSys Check says this card is deactivated."
    answer = client.post(
        f"/admin/verifications/{uuid4()}/reject",
        json={"notes": reason, "philsys_result": "deactivated"},
    )
    assert answer.status_code == 200 and answer.json()["verified"] is False
    assert storage.removed
    update = next(q for q in db.queries if q.startswith("update"))
    assert "- 'id_path' - 'selfie_path' - 'qr_path'" in update
    assert db.write("update")[2:] == (reason, "deactivated")
    assert pushes == [{"user_id": db.user_id, "approved": False, "notes": reason}]


def test_photos_that_cannot_be_deleted_hold_the_decision_back(
    client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    db, storage = _Db(), _Storage(failing="remove")
    _wire(_hub_admin(), db, storage)
    answer = client.post(f"/admin/verifications/{uuid4()}/approve", json=_VERIFIED)
    assert answer.status_code == 502
    assert db.pending and not any(q.startswith("update") for q in db.queries)
    assert pushes == []


def test_a_decided_review_is_not_decided_twice(
    client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    db, storage = _Db(pending=False), _Storage()
    _wire(_hub_admin(), db, storage)
    answer = client.post(f"/admin/verifications/{uuid4()}/approve", json=_VERIFIED)
    assert answer.status_code == 404
    assert storage.removed == [] and pushes == []


def test_a_failed_push_does_not_fail_the_decision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("FCM is down")

    monkeypatch.setattr(admin_routes, "notify_review_decided", broken)
    db, storage = _Db(), _Storage()
    _wire(_hub_admin(), db, storage)
    answer = client.post(f"/admin/verifications/{uuid4()}/approve", json=_VERIFIED)
    assert answer.status_code == 200


@pytest.mark.parametrize(
    ("status", "body", "gone"),
    [
        (200, {"message": "Successfully deleted"}, True),
        (404, {"message": "Not found"}, True),
        # What Storage really answers for a missing object.
        (400, {"statusCode": "404", "error": "not_found", "code": "NoSuchKey"}, True),
        (400, {"statusCode": "403", "error": "Unauthorized"}, False),
        (500, {"message": "Internal"}, False),
    ],
)
@pytest.mark.asyncio
async def test_a_photo_already_gone_is_not_an_error(
    status: int, body: dict[str, str], gone: bool
) -> None:
    """A reviewer retrying a decision finds the photos deleted; that must not stop them."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    async with httpx.AsyncClient(transport=transport) as http:
        storage = SupabaseStorageClient(http)
        if gone:
            await storage.remove(bucket="national-ids", path="u/selfie")
        else:
            with pytest.raises(ExternalServiceError):
                await storage.remove(bucket="national-ids", path="u/selfie")


def test_the_review_schemas_take_only_what_philsys_check_says() -> None:
    assert VerificationApproveRequest(philsys_result="verified")
    assert VerificationReviewRequest(philsys_result="unreadable", notes="Retake it")
    with pytest.raises(ValidationError):
        VerificationReviewRequest.model_validate({"philsys_result": "verified"})


# --------------------------------------------------------------------------- #
# Telling the resident
# --------------------------------------------------------------------------- #
class _Push:
    sent: list[dict[str, Any]] = []
    invalid: list[str] = []

    async def send_to_tokens(self, **kwargs: Any) -> Any:
        _Push.sent.append(kwargs)
        return type("Result", (), {"invalid_tokens": _Push.invalid})()


@pytest.fixture
def phone(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Push]]:
    _Push.sent, _Push.invalid = [], []
    monkeypatch.setattr(national_id, "PushService", _Push)
    yield _Push


class _Tokens(_Db):
    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self._note(query, args)
        return [{"fcm_token": "token-1"}]


@pytest.mark.asyncio
async def test_a_resident_asked_to_try_again_reads_why(phone: type[_Push]) -> None:
    db, user = _Tokens(), uuid4()
    reason = "Take the QR photo again, close up."
    assert await national_id.notify_review_decided(db, user, approved=False, notes=reason) == 1
    assert phone.sent[0]["body"] == reason
    assert phone.sent[0]["data"] == {"type": "national_id_reviewed"}
    assert any(q.startswith("insert into public.notifications") for q in db.queries)


@pytest.mark.asyncio
async def test_an_approved_resident_hears_their_photos_are_gone(phone: type[_Push]) -> None:
    await national_id.notify_review_decided(_Tokens(), uuid4(), approved=True)
    assert phone.sent[0]["title"] == "National ID verified"
    assert "deleted" in phone.sent[0]["body"]


@pytest.mark.asyncio
async def test_a_dead_device_token_is_retired(phone: type[_Push]) -> None:
    phone.invalid = ["token-1"]
    db = _Tokens()
    await national_id.notify_review_decided(db, uuid4(), approved=True)
    assert any(q.startswith("update public.device_tokens") for q in db.queries)
