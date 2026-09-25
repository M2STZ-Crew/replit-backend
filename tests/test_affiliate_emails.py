"""The affiliate form's emails (hermetic).

An applicant is told at once that their application arrived — before, nothing
was sent until an admin approved it, so a successful registration looked like
one that had failed. And on Render's free tier, where outbound SMTP on 587 is
blocked, mail goes out on 2525 and gives up in seconds rather than a minute.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_database, get_email_client
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.integrations import brevo_email
from app.main import app

_FORM = {
    "organization_name": "Visit www.spam.example for prizes",
    "agency_type": "fire_volunteer",
    "contact_email": "captain@brigade.example.com",
}


class _Db:
    def __init__(self, *, recently_emailed: bool) -> None:
        self.recently_emailed = recently_emailed

    async def fetchval(self, query: str, *args: Any) -> bool:
        return self.recently_emailed

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "id": uuid4(), "organization_name": args[0], "agency_type": args[1],
            "requested_by": None, "contact_name": None, "contact_email": args[2],
            "contact_phone": None, "address": None, "message": args[5],
            "status": "pending", "organization_id": None, "reviewed_by": None,
            "reviewed_at": None, "review_notes": None, "details": args[6],
            "created_at": now, "updated_at": now,
        }


class _Mail:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    async def send(self, **message: Any) -> None:
        if self.fail:
            raise ExternalServiceError("Failed to send email.")
        self.sent.append(message)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(db: _Db, mail: _Mail) -> None:
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_email_client] = lambda: mail


def test_the_applicant_is_told_it_arrived(client: TestClient) -> None:
    mail = _Mail()
    _wire(_Db(recently_emailed=False), mail)

    response = client.post("/affiliates/register", json=_FORM)

    assert response.status_code == 201, response.text
    assert [m["to"] for m in mail.sent] == ["captain@brigade.example.com"]
    assert "received" in mail.sent[0]["subject"].lower()
    # The form is public: nothing the applicant typed goes into the email.
    assert "spam" not in mail.sent[0]["html"] and "spam" not in mail.sent[0]["text"]


def test_one_acknowledgement_per_address_however_often_it_is_submitted(
    client: TestClient,
) -> None:
    mail = _Mail()
    _wire(_Db(recently_emailed=True), mail)

    assert client.post("/affiliates/register", json=_FORM).status_code == 201
    assert mail.sent == []


def test_a_failed_email_does_not_lose_the_application(client: TestClient) -> None:
    _wire(_Db(recently_emailed=False), _Mail(fail=True))

    assert client.post("/affiliates/register", json=_FORM).status_code == 201


def test_mail_goes_out_on_a_port_render_does_not_block() -> None:
    assert Settings.model_fields["brevo_smtp_port"].default == 2525


async def test_a_send_gives_up_in_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_send(message: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(brevo_email.aiosmtplib, "send", fake_send)
    mailer = brevo_email.BrevoEmailClient()
    mailer._settings = SimpleNamespace(  # type: ignore[assignment]
        brevo_configured=True, email_from_name="RepLiT", email_from="r@example.com",
        brevo_smtp_host="smtp-relay.brevo.com", brevo_smtp_port=2525,
        brevo_smtp_user="u", brevo_smtp_key="k",
    )

    await mailer.send(to="a@example.com", subject="s", html="<p>h</p>", text="t")

    assert seen["port"] == 2525
    assert 0 < seen["timeout"] <= 30
