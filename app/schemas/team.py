"""A coordinator's responder accounts (v1.12.4).

Coordinators create their own agency's Response Team accounts, reset their
passwords and deactivate them (app/api/routes/team.py). The address follows the
account directory's rule (app/services/responder_accounts.py). Since 6 Nov
2026 the coordinator gives the responder's own email too, and a link there
confirms it and sets the first password; an older app that sends none gets a
temporary password back, shown once, to hand over in person.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ResponderCreateRequest(BaseModel):
    """A new responder: the name the address is made from, and their own email."""

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60, description="The full surname.")
    personal_email: EmailStr | None = Field(
        default=None,
        description=(
            "The responder's own email: a link there confirms it and sets their "
            "password, and password resets go there later. Without one (an older "
            "app), a temporary password is returned instead."
        ),
    )
    mobile: str | None = Field(
        default=None, description="Philippine mobile, any format (older apps)."
    )


class TeamResponder(BaseModel):
    """One responder on a coordinator's roster."""

    id: UUID
    full_name: str | None = None
    email: str
    mobile: str | None = None
    agency_type: str
    is_active: bool = True
    responding: bool = Field(
        default=False, description="On a live response now (an active dispatch)."
    )
    created_at: datetime | None = None
    deactivated_at: datetime | None = None
    personal_email: str | None = None
    personal_email_verified: bool = False


class ResponderCredentials(BaseModel):
    """The new account's address, and how its password is set.

    With a personal email, the link to set it went there (``invite_email_sent``)
    and no password comes back. Otherwise, and for a reset, a temporary password,
    shown once and not stored anywhere the API can read it back.
    """

    responder: TeamResponder
    email: str
    temporary_password: str | None = None
    personal_email: str | None = None
    invite_email_sent: bool = False
    detail: str | None = None


class ResponderEmailPreview(BaseModel):
    """The address a responder with this name would get now."""

    email: str


# --------------------------------------------------------------------------- #
# The same accounts, as an Admin manages them (v1.12.49;
# app/api/routes/admin_responders.py)
# --------------------------------------------------------------------------- #
class AdminResponder(TeamResponder):
    """A responder on an Admin's Accounts screen: whose, and on which fire."""

    title: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    created_by_name: str | None = None
    responding_area_id: UUID | None = None
    responding_to: str | None = None
    responding_since: datetime | None = None


class AdminResponderCreate(BaseModel):
    """A new responder. The link to set a password goes to ``personal_email``."""

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60, description="The full surname.")
    personal_email: EmailStr
    mobile: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=80)
    organization_id: UUID | None = Field(
        default=None, description="For the central hub and the system Admin."
    )


class AdminResponderCreated(BaseModel):
    """The new responder, and whether the email to them went out."""

    responder: AdminResponder
    invite_email_sent: bool = False
    detail: str | None = None


class AdminResponderUpdate(BaseModel):
    """Only the fields sent change; an empty title or mobile clears it."""

    full_name: str | None = Field(default=None, max_length=200)
    mobile: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=80)
    organization_id: UUID | None = Field(
        default=None, description="Move them: the same agency, by the central hub."
    )


class AdminResponderLink(BaseModel):
    """Their own email, where none is on file or it was never confirmed."""

    personal_email: EmailStr | None = None


class AdminResponderLinkSent(BaseModel):
    """Where the password link went."""

    sent_to: str
