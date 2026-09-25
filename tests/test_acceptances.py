"""Who accepted an incident is read from where v11 writes it (hermetic).

v11 records every Accept in area_acceptances and no longer writes area_routes.
The consoles decide whether an agency still owes its Accept from
``accepted_agencies`` and the detail's ``acceptances``; reading only the routes
left both empty for every v11 incident, so the Observer Console offered police
and medical captains no Accept at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.api.routes import incidents
from app.schemas.incident import IncidentDetail

_AREA = uuid4()
_CAPTAIN = uuid4()
_OBSERVER = uuid4()


def test_accepted_agencies_reads_v11_acceptances() -> None:
    cols = incidents._SUMMARY_COLS
    accepted = cols[cols.index("as routed_agencies") :]
    assert "public.area_acceptances aa" in accepted
    # Older incidents were accepted through Admin routing; they still count.
    assert "rt.accepted_at is not null" in accepted
    # An Admin's Accept carries no agency and must not add a null to the list.
    assert "aa.agency is not null" in accepted


class _Db:
    """Answers the detail builder's four queries."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        return {
            "id": _AREA, "designation": "Area 7", "status": "en_route",
            "centroid_lat": 14.54, "centroid_lng": 121.0, "report_count": 2,
            "confidence_score": 0.8, "confidence_band": "high", "alarm_level": None,
            "active_dispatch_count": 0, "reported_at": self.now, "verified_at": self.now,
            "dispatched_at": None, "en_route_at": self.now, "arrived_at": None,
            "resolved_at": None, "post_incident_report_at": None, "closed_at": None,
            "rejected_at": None, "merged_at": None, "updated_at": self.now,
            "requested_agencies": ["fire_volunteer", "police"], "routed_agencies": [],
            "accepted_agencies": ["fire_volunteer", "police"], "route_count": 0,
            "n_score": 1.0, "s_score": 1.0, "v_score": 1.0, "version": 1,
            "parent_area_id": None, "verified_by": _CAPTAIN,
            "verified_by_name": "Ramon Dizon", "resolved_by": None,
            "resolved_by_name": None, "closed_by": None, "closed_by_name": None,
            "rejected_by": None, "rejected_by_name": None, "rejection_reason": None,
            "merged_by": None, "merged_by_name": None, "merged_into_area_id": None,
            "alarm_level_set_by": None, "alarm_level_set_at": None,
            "has_post_incident_report": False,
        }

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "from public.area_acceptances" in query:
            return [
                {"agency": "fire_volunteer", "user_id": _CAPTAIN, "user_name": "Ramon Dizon",
                 "organization_id": None, "organization_name": "Hercules Fire Brigade",
                 "is_first": True, "accepted_at": self.now},
                {"agency": "police", "user_id": _OBSERVER, "user_name": "Rowena Pascual",
                 "organization_id": None, "organization_name": "Pasay City Police Station",
                 "is_first": False, "accepted_at": self.now},
            ]
        return []


async def test_the_detail_lists_who_accepted() -> None:
    detail = await incidents.build_incident_detail(_Db(), _AREA)  # type: ignore[arg-type]

    assert isinstance(detail, IncidentDetail)
    assert [(a.agency, a.is_first) for a in detail.acceptances] == [
        ("fire_volunteer", True),
        ("police", False),
    ]
    assert detail.acceptances[1].user_name == "Rowena Pascual"
