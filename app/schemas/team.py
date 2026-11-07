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
