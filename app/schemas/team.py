"""A coordinator's responder accounts (v1.12.4).

Coordinators create their own agency's Response Team accounts, reset their
passwords and deactivate them (app/api/routes/team.py). The address follows the
account directory's rule (app/services/responder_accounts.py); the password is
generated and shown to the coordinator once, to hand over in person.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ResponderCreateRequest(BaseModel):
    """A new responder: the name the address is made from, and an optional mobile."""

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60, description="The full surname.")
    mobile: str | None = Field(default=None, description="Philippine mobile, any format.")


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


class ResponderCredentials(BaseModel):
    """What the coordinator hands over: the address and a temporary password.

    Shown once. The password is not stored anywhere the API can read it back.
    """

    responder: TeamResponder
    email: str
    temporary_password: str


class ResponderEmailPreview(BaseModel):
    """The address a responder with this name would get now."""

    email: str
