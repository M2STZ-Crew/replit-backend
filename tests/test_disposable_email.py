"""Disposable Email Address (DEA) detection (hermetic, 7 Nov 2026).

What these pin:
- an address from a throwaway service is found, written any way, on a
  subdomain too, and the providers people use never are;
- the settings refuse more domains or lift ones the list has wrong;
- the bundled list is the community one, whole, and says where it came from;
- every route that takes an email RepLiT relies on refuses one with a 400
  ``disposable_email`` naming the field, before anything is looked up, made
  or sent.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, get_args
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    CoordinatorManager,
    get_auth_client,
    get_current_user,
    get_database,
    get_email_client,
)
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import AuthenticatedUser
from app.services import disposable_email as dea
from app.services.disposable_email import (
    ALWAYS_ALLOWED,
    LIST_PATH,
    DisposableEmailError,
    disposable_domain,
    ensure_not_disposable,
    is_disposable,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "disposable_email_domains_extra", "")
    monkeypatch.setattr(s, "disposable_email_domains_allowed", "")
    monkeypatch.setattr(s, "require_citizen_phone_verification", False)


# --------------------------------------------------------------------------- #
# Finding one
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("email", "service"),
    [
        ("juan@mailinator.com", "mailinator.com"),
        ("  Juan.Dela.Cruz@MAILINATOR.COM ", "mailinator.com"),
        ("juan@inbox.mailinator.com", "mailinator.com"),
        ("juan@mailinator.com.", "mailinator.com"),
        ("juan@10minutemail.com", "10minutemail.com"),
        ("juan@yopmail.com", "yopmail.com"),
        ("juan@guerrillamail.com", "guerrillamail.com"),
        ("juan@sharklasers.com", "sharklasers.com"),
        ("juan@temp-mail.org", "temp-mail.org"),
        ("juan@maildrop.cc", "maildrop.cc"),
    ],
)
def test_a_throwaway_service_is_found(email: str, service: str) -> None:
    assert disposable_domain(email) == service
    assert is_disposable(email)


@pytest.mark.parametrize(
    "email",
    [
        "juan@gmail.com",
        "juan@yahoo.com.ph",
        "juan@outlook.com",
        "juan@icloud.com",
        "juan@proton.me",
        "juan@up.edu.ph",
        "teacher@deped.gov.ph",
        "obryan.fircor@replit.com",
        "juan@example.com",
    ],
)
def test_the_providers_people_use_pass(email: str) -> None:
    assert disposable_domain(email) is None


@pytest.mark.parametrize("email", ["", "juan", "juan@", "juan@localhost", "juan@.com", "@"])
def test_what_is_not_an_address_is_not_a_burner(email: str) -> None:
    assert disposable_domain(email) is None


def test_the_providers_people_use_are_never_refused_whatever_the_list_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dea, "bundled_domains", lambda: frozenset({"gmail.com", "burner.test"}))
    assert disposable_domain("juan@gmail.com") is None
    assert disposable_domain("juan@burner.test") == "burner.test"
    for provider in ALWAYS_ALLOWED:
        assert disposable_domain(f"someone@{provider}") is None


def test_the_settings_refuse_more_and_lift_what_the_list_has_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "disposable_email_domains_extra", " Burner.Example. , other.example")
    assert disposable_domain("juan@burner.example") == "burner.example"
    assert disposable_domain("juan@x.other.example") == "other.example"
    monkeypatch.setattr(s, "disposable_email_domains_allowed", "mailinator.com")
    assert disposable_domain("juan@mailinator.com") is None


def test_a_domain_in_another_script_is_looked_up_in_its_ascii_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert disposable_domain("juan@bücher.example") is None
    monkeypatch.setattr(get_settings(), "disposable_email_domains_extra", "xn--bcher-kva.example")
    assert disposable_domain("juan@bücher.example") == "xn--bcher-kva.example"


def test_refusing_says_which_service_and_which_field() -> None:
    with pytest.raises(DisposableEmailError) as caught:
        ensure_not_disposable("juan@mailinator.com", field="personal_email")
    assert caught.value.status_code == 400
    assert caught.value.error_code == "disposable_email"
    assert caught.value.details == {"field": "personal_email", "domain": "mailinator.com"}
    assert "mailinator.com" in caught.value.message
    with pytest.raises(DisposableEmailError) as custom:
        ensure_not_disposable("juan@mailinator.com", message="Not this one.")
    assert custom.value.message == "Not this one."
    ensure_not_disposable(None)
    ensure_not_disposable("")
    ensure_not_disposable("juan@gmail.com")


# --------------------------------------------------------------------------- #
# The bundled list
# --------------------------------------------------------------------------- #
def test_the_bundled_list_is_the_community_one_whole() -> None:
    text = LIST_PATH.read_text(encoding="utf-8")
    domains = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(domains) >= 5000
    assert len(domains) == len(set(domains)) == len(dea.bundled_domains())
    pattern = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
    assert all(pattern.match(d) for d in domains)
    assert "mailinator.com" in dea.bundled_domains()


def test_the_bundled_list_says_where_it_came_from() -> None:
    header = LIST_PATH.read_text(encoding="utf-8").split("\n# Refresh", 1)[0]
    assert "github.com/disposable-email-domains/disposable-email-domains" in header
    assert "CC0" in header


# --------------------------------------------------------------------------- #
# The routes: refused before anything is looked up, made or sent
# --------------------------------------------------------------------------- #
class _Untouchable:
    """A database, auth or email client that must not be used."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> Any:
        raise AssertionError(f"the {self._name} was used: {attr}")


def _user(role: str, **kw: Any) -> AuthenticatedUser:
    return AuthenticatedUser(id=uuid4(), role=role, phone_verified=True, **kw)


BURNER = "juan@mailinator.com"
COORDINATOR_MANAGER = get_args(CoordinatorManager)[1].dependency

CASES = [
    pytest.param(
        "/auth/signup",
        "post",
        None,
        {"email": BURNER, "password": "long-enough-1", "full_name": "Juan dela Cruz"},
        "email",
        id="sign-up",
    ),
    pytest.param(
        "/verification/email/request",
        "post",
        _user("general_user", email=BURNER),
        None,
        "email",
        id="email link",
    ),
    pytest.param(
        "/auth/me/personal-email",
        "put",
        _user("response_team", email="jdelacruz.firres@replit.com", agency_type="fire_volunteer"),
        {"email": BURNER},
        "email",
        id="staff personal email",
    ),
    pytest.param(
        "/admin/coordinators",
        "post",
        "coordinator-manager",
        {"first_name": "Odyssey", "last_name": "Bryan", "personal_email": BURNER},
        "personal_email",
        id="new coordinator",
    ),
    pytest.param(
        "/team/responders",
        "post",
        _user("sub_admin", agency_type="fire_volunteer", primary_org_id=uuid4()),
        {"first_name": "Juan", "last_name": "dela Cruz", "personal_email": BURNER},
        "personal_email",
        id="new responder",
    ),
    pytest.param(
        "/affiliates",
        "post",
        _user("general_user", email="captain@gmail.com"),
        {"organization_name": "Barangay 1", "agency_type": "barangay", "contact_email": BURNER},
        "contact_email",
        id="affiliate request",
    ),
    pytest.param(
        "/affiliates/register",
        "post",
        None,
        {"organization_name": "Barangay 1", "agency_type": "barangay", "contact_email": BURNER},
        "contact_email",
        id="affiliate application",
    ),
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(("path", "method", "user", "body", "field"), CASES)
def test_every_route_refuses_a_burner_before_anything_is_done(
    client: TestClient,
    path: str,
    method: str,
    user: AuthenticatedUser | str | None,
    body: dict[str, Any] | None,
    field: str,
) -> None:
    app.dependency_overrides[get_database] = lambda: _Untouchable("database")
    app.dependency_overrides[get_auth_client] = lambda: _Untouchable("auth client")
    app.dependency_overrides[get_email_client] = lambda: _Untouchable("email client")
    if user == "coordinator-manager":
        app.dependency_overrides[COORDINATOR_MANAGER] = lambda: _user(
            "admin", agency_type="fire_volunteer", primary_org_id=uuid4()
        )
    elif isinstance(user, AuthenticatedUser):
        app.dependency_overrides[get_current_user] = lambda: user

    r = client.request(method, path, json=body)

    assert r.status_code == 400, r.text
    assert r.json()["error"] == "disposable_email"
    assert r.json()["details"] == {"field": field, "domain": "mailinator.com"}


def test_an_account_already_on_a_burner_is_told_why_it_cannot_confirm(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_database] = lambda: _Untouchable("database")
    app.dependency_overrides[get_email_client] = lambda: _Untouchable("email client")
    app.dependency_overrides[get_current_user] = lambda: _user("general_user", email=BURNER)

    r = client.post("/verification/email/request")

    assert r.json()["message"] == (
        "Your email is from a temporary email service, so it cannot be confirmed."
    )
