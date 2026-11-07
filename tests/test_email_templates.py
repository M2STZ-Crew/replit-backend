"""Every RepLiT email: one branded layout, a plain-text twin, escaped values (hermetic).

v1.12.19 put the five emails (verify your email, reset your password, the
affiliate's "received" and "approved", the new Coordinator's invitation) on
one layout (app/services/email_layout.py). These check what each must keep:
its link, in the button and written out; how long the link lasts; a
plain-text part with the same words; and that nothing a person typed can add
markup. Rendering in real mail clients is checked by hand, not here.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_database, get_email_client
from app.api.routes import affiliates, password_reset, verification
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import staff_links
from app.services.email_layout import (
    LOGO_URL,
    EmailAction,
    RenderedEmail,
    render_email,
)

_LINK = "https://auth.example.com/verify?token=abc&type=recovery&redirect_to=x"
_LINK_IN_HTML = _LINK.replace("&", "&amp;")


def _emails() -> dict[str, RenderedEmail]:
    return {
        "verify": verification._verification_email("Ana Cruz", _LINK),
        "reset": password_reset._reset_email(_LINK),
        "received": affiliates._received_email(),
        "approved": affiliates._approval_email("Hercules Fire Brigade", _LINK),
        "invite": staff_links.welcome_email(
            name="Ana Cruz",
            role="Coordinator",
            organization="Hercules Fire Brigade",
            address="acruz.fircor@replit.com",
            link=_LINK,
            made_by="Your organization's Admin",
        ),
        "staff_reset": staff_links.reset_email(
            address="acruz.fircor@replit.com", link=_LINK
        ),
        "staff_verify": staff_links.verify_email(
            address="acruz.fircor@replit.com", link=_LINK
        ),
    }


@pytest.mark.parametrize(
    "name",
    ["verify", "reset", "received", "approved", "invite", "staff_reset", "staff_verify"],
)
def test_every_email_has_the_layout_and_a_text_twin(name: str) -> None:
    message = _emails()[name]
    html, text = message.html, message.text

    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en"' in html
    assert 'role="presentation"' in html and "max-width:600px" in html
    assert LOGO_URL in html and ">RepLiT</td>" in html
    assert '<meta name="color-scheme" content="light dark">' in html
    assert "<script" not in html.lower()
    # Why it came, and who sent it, in both bodies.
    assert "You are receiving this email because" in html
    assert "You are receiving this email because" in text
    assert text.startswith("RepLiT\n\n")
    assert "<" not in text, "the plain-text part carries no markup"


@pytest.mark.parametrize(
    "name", ["verify", "reset", "approved", "invite", "staff_reset", "staff_verify"]
)
def test_the_link_is_the_button_and_written_out(name: str) -> None:
    message = _emails()[name]
    assert message.html.count(f'href="{_LINK_IN_HTML}"') == 2
    assert f">{_LINK_IN_HTML}</a>" in message.html
    assert _LINK in message.text


def test_the_link_lifetimes_are_stated_unchanged() -> None:
    emails = _emails()
    assert "24 hours" in emails["verify"].html and "24 hours" in emails["verify"].text
    for name in ("reset", "approved", "staff_reset"):
        assert "one hour" in emails[name].html and "one hour" in emails[name].text
    # A staff welcome waits three days: the person may not open it that hour.
    for name in ("invite", "staff_verify"):
        assert "three days" in emails[name].html and "three days" in emails[name].text


def test_the_public_forms_email_carries_nothing_typed() -> None:
    # It takes no arguments at all, and links to nothing.
    assert "href=" not in affiliates._received_email().html


def test_a_name_cannot_add_markup() -> None:
    sly = '<a href="https://evil.example">Ana</a> & "Co"'
    for message in (
        verification._verification_email(sly, _LINK),
        affiliates._approval_email(sly, _LINK),
        staff_links.welcome_email(
            name=sly, role="Coordinator", organization=sly, address="x@replit.com",
            link=_LINK, made_by="An Admin",
        ),
    ):
        assert "evil.example\">Ana</a>" not in message.html
        assert "&lt;a href=&quot;https://evil.example&quot;&gt;Ana&lt;/a&gt;" in message.html
        assert sly in message.text


def test_a_link_cannot_break_out_of_its_attribute() -> None:
    message = render_email(
        preheader="p",
        heading="h",
        paragraphs=["x"],
        reason="r",
        action=EmailAction("Go", 'https://x.example/"><script>alert(1)</script>'),
    )
    assert "<script>" not in message.html
    assert 'href="https://x.example/&quot;&gt;&lt;script&gt;' in message.html


def test_no_name_greets_without_one() -> None:
    assert "Hello,</p>" in verification._verification_email(None, _LINK).html
    assert "Hello Ana Cruz," in verification._verification_email("Ana Cruz", _LINK).text


def test_the_preheader_is_hidden_and_first() -> None:
    html = password_reset._reset_email(_LINK).html
    body = html.split("<body", 1)[1]
    hidden = re.search(r'<div style="display:none;[^"]*">([^<]*)</div>', body)
    assert hidden is not None
    assert hidden.group(1).startswith("Choose a new password for your RepLiT account.")


# ------------------------------------------------- the verification route ---
class _Db:
    """Enough of the database for one email link: no link yet, every write taken."""

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_Db]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "INSERT 0 1"


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **message: Any) -> None:
        self.sent.append(message)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_the_verification_email_now_has_a_plain_text_part(client: TestClient) -> None:
    mail = _Mail()
    user = AuthenticatedUser(
        id=uuid4(),
        role="general_user",
        email="ana@example.com",
        full_name="Ana Cruz",
        phone_verified=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_database] = lambda: _Db()
    app.dependency_overrides[get_email_client] = lambda: mail

    r = client.post("/verification/email/request")

    assert r.status_code == 200, r.text
    assert [m["to"] for m in mail.sent] == ["ana@example.com"]
    assert mail.sent[0]["subject"] == "Verify your RepLiT email"
    sent_link = re.search(
        r"https?://\S+/verification/email/confirm\?token=\S+", mail.sent[0]["text"]
    )
    assert sent_link is not None
    assert f'href="{sent_link.group(0)}"' in mail.sent[0]["html"]
    assert "Hello Ana Cruz," in mail.sent[0]["text"]
