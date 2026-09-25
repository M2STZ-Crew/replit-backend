"""The test push says what actually happened (hermetic).

A server that could not reach FCM used to answer a test push with "Sent to 0
device(s); 0 failed." — a success message for a notification that never left.
People went looking for the fault on their phone. These pin the honest answers.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database, get_push_service
from app.integrations import fcm
from app.integrations.fcm import PushResult
from app.main import app
from app.schemas.auth import AuthenticatedUser


class _Db:
    """Just enough of the database for the device routes."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.deactivated: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, str]]:
        return [{"fcm_token": t} for t in self.tokens]

    async def execute(self, query: str, *args: Any) -> str:
        self.deactivated.extend(args[0])
        return "UPDATE"


class _Push:
    def __init__(self, *, available: bool, result: PushResult | None = None) -> None:
        self.is_available = available
        self.result = result or PushResult()
        self.sent_to: list[str] = []

    async def send_to_tokens(self, *, tokens: list[str], **_: Any) -> PushResult:
        self.sent_to = tokens
        return self.result


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, push: _Push) -> None:
    user = AuthenticatedUser(id=uuid4(), role="general_user")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_push_service] = lambda: push


# --------------------------------------------------------------------------- #
# The endpoint
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "state,phrase",
    [
        ("unconfigured", "credentials are missing"),
        ("failed", "credentials did not load"),
    ],
)
def test_a_server_that_cannot_push_says_so(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    phrase: str,
) -> None:
    monkeypatch.setattr(fcm, "_fcm_state", state)
    _wire(_Db(tokens=["tok-on-a-real-phone"]), _Push(available=False))

    resp = client.post("/devices/test", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 503
    body = resp.json()
    text = str(body)
    assert phrase in text
    assert "Your phone is fine" in text
    assert "Sent to 0" not in text, "the old message read as a success"


def test_a_working_server_reports_real_counts(client: TestClient) -> None:
    push = _Push(available=True, result=PushResult(success_count=1, failure_count=0))
    _wire(_Db(tokens=["tok-1"]), push)

    resp = client.post("/devices/test", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    assert resp.json()["message"] == "Sent to 1 device(s); 0 failed."
    assert push.sent_to == ["tok-1"]


def test_dead_tokens_are_retired(client: TestClient) -> None:
    db = _Db(tokens=["tok-live", "tok-dead"])
    push = _Push(
        available=True,
        result=PushResult(success_count=1, failure_count=1, invalid_tokens=["tok-dead"]),
    )
    _wire(db, push)

    resp = client.post("/devices/test", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200
    assert db.deactivated == ["tok-dead"]


def test_no_registered_phone_is_its_own_answer(client: TestClient) -> None:
    _wire(_Db(tokens=[]), _Push(available=True))

    resp = client.post("/devices/test", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 400
    assert "No active device tokens" in str(resp.json())


# --------------------------------------------------------------------------- #
# Why FCM would not start
# --------------------------------------------------------------------------- #
def _settings(**values: str) -> SimpleNamespace:
    json_ = values.get("json", "")
    file_ = values.get("file", "")
    return SimpleNamespace(
        fcm_credentials_json=json_,
        fcm_credentials_file=file_,
        fcm_configured=bool(json_ or file_),
    )


def test_no_credentials_reads_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fcm, "_fcm_app", None)
    monkeypatch.setattr(fcm, "get_settings", lambda: _settings())
    fcm.init_fcm()
    assert fcm.fcm_status() == "unconfigured"


def test_a_laptop_file_path_on_a_host_reads_as_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The usual way push breaks on a deploy: FCM_CREDENTIALS_FILE copied from a
    # laptop's .env, naming a gitignored file that was never deployed.
    monkeypatch.setattr(fcm, "_fcm_app", None)
    monkeypatch.setattr(
        fcm, "get_settings", lambda: _settings(file="not-deployed-service-account.json")
    )
    fcm.init_fcm()
    assert fcm.fcm_status() == "failed"


def test_a_relative_path_resolves_from_the_repo_not_the_cwd() -> None:
    resolved = fcm._credentials_path("firebase-service-account.json")
    assert resolved.parent == Path(fcm.__file__).resolve().parents[2]


def test_readiness_names_the_push_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fcm, "_fcm_state", "failed")
    resp = client.get("/health/ready")
    assert resp.json()["checks"]["push"] == "failed"
