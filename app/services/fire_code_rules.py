"""Which fire codes a responder may press, and where (v1.12.48).

22 Nov 2026: any responder of any agency, on a fire or not, could press any
code, so one wrong press could have called a fire under control. Answered
("Coordinators declare"): responders press only on fires they are on, and
crews outside the fire service only ask for more units or report a casualty.

- On it: an active response on that incident.
- Fire Volunteer and BFP crews: every code.
- Other agencies' crews: FC-7 (more units) and FC-8 (a casualty).
- Fire out completes every response, so FC-4 (overhauling) and FC-5 (returning
  to station) are also open to a fire crew whose response it completed.

Coordinators and Admins are decided in the route: Fire Volunteer and BFP
coordinators, and Admins with ``codes.press``. The app mirrors this
(lib/models/fire_code_rules.dart).
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ForbiddenError
from app.db.session import Database
from app.schemas.auth import AuthenticatedUser
from app.services.access import FIRE_AGENCIES

CALL_FOR_HELP = frozenset({"FC-7", "FC-8"})
AFTER_FIRE = frozenset({"FC-4", "FC-5"})

_ON_IT_SQL = """
select exists (
  select 1 from public.dispatch_logs
   where area_id = $1 and responder_id = $2 and status::text = any($3::text[])
)
"""


def responses_that_count(code_number: str) -> list[str]:
    """The dispatch statuses that make a responder on the fire for this code."""
    return ["active", "completed"] if code_number in AFTER_FIRE else ["active"]


async def assert_responder_may_press(
    db: Database, user: AuthenticatedUser, area_id: UUID | None, code_number: str
) -> None:
    """Refuse a responder's press outside the rules above."""
    if user.agency_type not in FIRE_AGENCIES and code_number not in CALL_FOR_HELP:
        raise ForbiddenError(
            "Your team can send FC-7 (more units) and FC-8 (a casualty). "
            "The other fire codes are the fire service's."
        )
    if area_id is None:
        raise ForbiddenError("Press fire codes from the fire you are on.")
    on_it = await db.fetchval(_ON_IT_SQL, area_id, user.id, responses_that_count(code_number))
    if not on_it:
        raise ForbiddenError("You can press fire codes only on a fire you are on.")
