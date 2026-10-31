"""What an Admin may do in the one Admin console (PRD v13/v14 §4.6).

Every participating organisation has its own Admin, and they all sign in to
the same console. What each may do is decided here, from attributes of the
account and its organisation — the console only draws what this module
allows, and every route that acts checks it again (PRD §1.4: the server is the
authority; UI predicates are a courtesy).

The rules are REPLIT (MAIN) pass 6, A00 "Four permission variants":

* **Every Admin** sees every active incident (dashboard, list, map) and
  acknowledges the ones its agency was asked for — Fire Volunteer and BFP for
  Fire, everyone else for their own agency. Elsewhere it follows the incident
  but cannot act on it (A25, view only). It decides an overlap only when both
  Areas were routed to it, deletes water resources, creates and turns off its
  own organisation's Coordinators, and reads the reports of incidents its
  organisation took part in. It never rejects, marks fire out, dispatches or
  drives: those are the Coordinators', on the mobile app (§4.5.2, §4.6.1).
* **Fire Volunteer Admin** also asks BFP to raise the alarm (A45).
* **BFP Admin** (the singleton) decides those requests and sets the level
  (A46, A46b; §3.4 "only authority allowed to execute alarm escalation").
* **Fire Volunteer and BFP Admins** look after the map layers every
  organisation shares (Map settings): they are the fire service's working map,
  and PRD §4.9.6 gives water resources to the Fire Volunteers. The layers were
  the system account's alone, and the directory of 28 Oct 2026 has none.
* **The central hub** (Barangay 76, ``organizations.is_central_hub``) is a
  Barangay Admin that also reviews affiliate applications and National IDs,
  and looks after those map layers too. "Nothing here makes the central hub a
  superuser": it acts on Barangay's incidents like any Barangay Admin.

An Admin with no organisation is the **system** account the console had
before v13 (admin@replit.com): it keeps the full authority it always had, so
nothing that worked stops working. It is not one of the four variants; it is
how the system owner runs the pilot.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.schemas.auth import AuthenticatedUser

FIRE_AGENCIES = ("fire_volunteer", "bfp")

# What an Admin may do. GET /auth/me returns the set, so the console draws from
# the same list the routes check.
ACKNOWLEDGE = "incidents.acknowledge"
DECIDE_OVERLAPS = "incidents.overlaps"
COORDINATE = "incidents.coordinate"  # reject, fire out, dispatch: Coordinators' acts
REVIEW_AFFILIATES = "affiliates.review"
REVIEW_IDS = "verifications.review"
MANAGE_MAP = "map.manage"  # add or change map layers, imports, layer requests
DELETE_WATER = "water.delete"
REQUEST_ALARM = "alarm.request"
DECIDE_ALARM = "alarm.decide"
CREATE_COORDINATORS = "accounts.coordinators"
MANAGE_ANY_ACCOUNT = "accounts.any"  # any role, any organisation (POST /admin/users)
ALL_ORGANIZATIONS = "organizations.all"  # read any organisation's people and equipment
ALL_RECORDS = "records.all"  # every report, summary and audit entry, unredacted

_EVERY_ADMIN = frozenset({ACKNOWLEDGE, DECIDE_OVERLAPS, DELETE_WATER, CREATE_COORDINATORS})

_SYSTEM = frozenset(
    {
        ACKNOWLEDGE,
        DECIDE_OVERLAPS,
        COORDINATE,
        REVIEW_AFFILIATES,
        REVIEW_IDS,
        MANAGE_MAP,
        DELETE_WATER,
        CREATE_COORDINATORS,
        MANAGE_ANY_ACCOUNT,
        ALL_ORGANIZATIONS,
        ALL_RECORDS,
    }
)

_AGENCY_WORD = {
    "fire_volunteer": "Fire",
    "bfp": "Fire",
    "police": "Police",
    "medical": "Medical",
    "barangay": "Barangay",
}


@dataclass(frozen=True)
class AdminAccess:
    """One Admin's standing: which variant, for which organisation, may do what."""

    variant: str  # system | central | fire_volunteer | bfp | police | medical | barangay
    organization_id: UUID | None
    organization_name: str | None
    agency: str | None
    # Agencies whose incidents this Admin acts on; None means every incident.
    act_agencies: tuple[str, ...] | None
    permissions: frozenset[str]

    @property
    def is_system(self) -> bool:
        return self.variant == "system"

    @property
    def scope(self) -> str:
        """system | central | organization — which sidebar the console draws."""
        if self.variant in ("system", "central"):
            return self.variant
        return "organization"

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def acts_on(self, requested_agencies: Iterable[str]) -> bool:
        """True when an incident that asked for ``requested_agencies`` is routed to us."""
        if self.act_agencies is None:
            return True
        return bool(set(self.act_agencies) & set(requested_agencies or ()))

    def routed_word(self) -> str:
        """How the console names what we answer for: "Fire", "Police", …"""
        return _AGENCY_WORD.get(self.agency or "", "your agency")


def admin_access(user: AuthenticatedUser) -> AdminAccess | None:
    """The Admin's access, or None for anyone who is not an Admin.

    Reads only the account and the organisation columns the user was loaded
    with (deps.get_current_user), so it is cheap to call on every check.
    """
    if user.role != "admin":
        return None
    if user.primary_org_id is None:
        return AdminAccess(
            variant="system",
            organization_id=None,
            organization_name=None,
            agency=None,
            act_agencies=None,
            permissions=_SYSTEM,
        )
    agency = user.org_agency_type
    # An organisation that is gone or turned off leaves its Admin able to look,
    # not to act: failing closed beats guessing what it should still do.
    if agency is None or user.org_is_active is False:
        return AdminAccess(
            variant=agency or "organization",
            organization_id=user.primary_org_id,
            organization_name=user.org_name,
            agency=agency,
            act_agencies=(),
            permissions=frozenset(),
        )
    permissions = set(_EVERY_ADMIN)
    if agency in FIRE_AGENCIES:
        permissions.add(MANAGE_MAP)
    if agency == "fire_volunteer":
        permissions.add(REQUEST_ALARM)
    if agency == "bfp":
        permissions.add(DECIDE_ALARM)
    variant = agency
    if user.org_is_central_hub:
        variant = "central"
        permissions |= {REVIEW_AFFILIATES, REVIEW_IDS, ALL_ORGANIZATIONS, MANAGE_MAP}
    return AdminAccess(
        variant=variant,
        organization_id=user.primary_org_id,
        organization_name=user.org_name,
        agency=agency,
        act_agencies=FIRE_AGENCIES if agency in FIRE_AGENCIES else (agency,),
        permissions=frozenset(permissions),
    )


def acting_agency(user: AuthenticatedUser) -> str | None:
    """The agency an act is recorded under: the account's own, or for an
    organisation's Admin (who has none — users_agency_consistency) its
    organisation's."""
    if user.agency_type:
        return user.agency_type
    if user.role == "admin" and user.primary_org_id is not None:
        return user.org_agency_type
    return None


def is_organization_admin(user: AuthenticatedUser) -> bool:
    """An Admin bound to one organisation (anything but the system account)."""
    access = admin_access(user)
    return access is not None and not access.is_system
