"""What residents' alerts say, in the language each chose (5 Nov 2026, issue list 1.5).

The app is in English or in Tagalog at CEFR B1 (users.language, set by the app
with PUT /auth/me/language), and the pushes and inbox rows a resident gets
follow it: the 100 m neighbourhood alert, the news on a report they filed, the
National ID answer and the test alert. Staff alerts stay in English.

Tagalog here is the app's: everyday Metro Manila Tagalog in short sentences,
keeping the English words people use anyway (report, responder, app).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import Database

log = get_logger(__name__)

Language = Literal["en", "tl"]
LANGUAGES: tuple[Language, ...] = ("en", "tl")
DEFAULT_LANGUAGE: Language = "en"


def language_of(raw: object) -> Language:
    """A stored value as a language; anything unknown reads as English."""
    return "tl" if raw == "tl" else "en"


async def languages_of(db: Database, user_ids: Sequence[UUID]) -> dict[UUID, Language]:
    """Each user's language. Users not found read as English.

    Best-effort, like the alerts it serves: if the lookup fails, everyone reads
    as English rather than the alert not going at all.
    """
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    try:
        rows = await db.fetch(
            "select id, language from public.users where id = any($1::uuid[])", ids
        )
        found = {r["id"]: language_of(r["language"]) for r in rows}
    except Exception:
        log.warning("user_language_lookup_failed", users=len(ids), exc_info=True)
        found = {}
    return {uid: found.get(uid, DEFAULT_LANGUAGE) for uid in ids}


def by_language(languages: dict[UUID, Language]) -> dict[Language, list[UUID]]:
    """The users grouped by language, each group in the order given."""
    groups: dict[Language, list[UUID]] = {}
    for uid, language in languages.items():
        groups.setdefault(language, []).append(uid)
    return groups


# The 100 m neighbourhood alert (app/workers/neighborhood.py). The Tagalog is
# the alert PRD v14 §4.2 was written with.
NEIGHBOUR_ALERT: dict[Language, tuple[str, str]] = {
    "en": (
        "Fire alert",
        "Is there a fire near you? Tap this alert to send your own report.",
    ),
    "tl": (
        "Alerto sa Sunog",
        "May sunog ba sa lugar na ito? I-click ang notif na ito para makapag-submit "
        "ka rin ng report!",
    ),
}

# News on a report the resident filed (app/services/incident_notify.py).
REPORTER_MESSAGES: dict[str, dict[Language, tuple[str, str]]] = {
    "incident_verified": {
        "en": (
            "Report verified",
            "Your fire report was verified. Responders are being assigned.",
        ),
        "tl": (
            "Na-verify ang report mo",
            "Na-verify na ang fire report mo. May mga responder nang ipinapadala.",
        ),
    },
    "responder_dispatched": {
        "en": (
            "Responders dispatched",
            "A response team has been dispatched to the incident you reported.",
        ),
        "tl": (
            "May responder nang ipinadala",
            "May response team nang ipinadala sa insidenteng ini-report mo.",
        ),
    },
    "incident_en_route": {
        "en": (
            "Help is on the way",
            "Responders are on the way to the fire you reported. Open RepLiT to see them.",
        ),
        "tl": (
            "Papunta na ang tulong",
            "Papunta na ang mga responder sa sunog na ini-report mo. Buksan ang "
            "RepLiT para makita sila.",
        ),
    },
    "incident_arrived": {
        "en": (
            "Responders on scene",
            "Responders have arrived at the incident you reported.",
        ),
        "tl": (
            "Nandiyan na ang mga responder",
            "Dumating na ang mga responder sa insidenteng ini-report mo.",
        ),
    },
    "incident_resolved": {
        "en": (
            "Incident resolved",
            "The incident you reported has been resolved. Stay safe.",
        ),
        "tl": (
            "Tapos na ang insidente",
            "Naayos na ang insidenteng ini-report mo. Mag-ingat palagi.",
        ),
    },
    "incident_rejected": {
        "en": (
            "Report closed",
            "Your report has been reviewed and closed.",
        ),
        "tl": (
            "Sarado na ang report",
            "Nasuri at isinara na ang report mo.",
        ),
    },
}


def fire_verified(language: Language, street: str | None) -> tuple[str, str]:
    """Every resident, once staff verify a fire (app/services/fire_broadcast.py,
    v1.12.38): where it is, and what to do. Asking "Do you see it too?" is left
    to the residents within 100 m (NEIGHBOUR_ALERT)."""
    street = (street or "").strip()
    if language == "tl":
        where = f"sa {street}" if street else "sa Pasay"
        return (
            "Kumpirmadong sunog",
            f"Kinumpirma ng mga responder ang sunog {where}. Lumayo sa lugar at "
            "bigyang-daan ang mga trak ng bumbero. I-tap para makita kung saan.",
        )
    where = f"on {street}" if street else "in Pasay"
    return (
        "Fire verified",
        f"Responders verified a fire {where}. Stay away from the area and keep the "
        "roads clear for fire trucks. Tap to see where.",
    )


def strike_message(
    language: Language,
    event: str,
    *,
    step: int,
    awaiting: bool,
    until: str,
    can_report: bool,
) -> tuple[str, str]:
    """A resident's news about a prank strike (app/services/report_strikes.py,
    v1.12.41): what it stops, until when, and that 911 still works. Never who
    gave it. ``until`` is already in the reader's words ("20 Nov, 3:15 PM")."""
    tl = language == "tl"
    if event in ("given", "confirmed"):
        if awaiting:
            if tl:
                return (
                    "Naka-pause ang pag-report habang sinusuri",
                    "Nakita ng staff na prank ulit ang isang report mo. Susuriin pa ito "
                    "ng isa pang staff. Kung may emergency, tumawag sa 911.",
                )
            return (
                "Reporting paused while staff check",
                "Staff found another of your reports was a prank. A second staff member "
                "will check it. In an emergency, call 911.",
            )
        if step >= 4:
            if tl:
                return (
                    "Hindi ka na makakapag-report",
                    "Dahil sa paulit-ulit na prank na report, tinanggal na ang pag-report "
                    "sa account mo. Makakatanggap ka pa rin ng fire alert at puwede kang "
                    "tumawag sa 911. Buksan ang RepLiT para mag-apela.",
                )
            return (
                "You can no longer send reports",
                "After repeated prank reports, reporting is removed from your account. You "
                "still get fire alerts and can call 911. Open RepLiT to appeal.",
            )
        if tl:
            return (
                f"Naka-pause ang pag-report hanggang {until}",
                "Nakita ng staff na prank ang isang report mo. Buksan ang RepLiT para "
                "makita kung bakit, o para mag-apela. Kung may emergency, tumawag sa 911.",
            )
        return (
            f"Reporting paused until {until}",
            "Staff found that a report you sent was a prank. Open RepLiT to see why, or "
            "to appeal. In an emergency, call 911.",
        )
    if event == "declined":
        if tl:
            return (
                "Tinanggal na ang strike",
                "Sinuri ng isa pang staff ang report mo at tinanggal ang strike.",
            )
        return (
            "Strike removed",
            "A second staff member checked your report and removed the strike.",
        )
    if event == "overturned":
        if tl:
            again = " Puwede ka na ulit mag-report." if can_report else ""
            return "Tinanggap ang apela mo", f"Tinanggal na ang strike.{again}"
        again = " You can send reports again." if can_report else ""
        return "Appeal accepted", f"The strike was removed.{again}"
    if tl:
        return (
            "Hindi tinanggap ang apela mo",
            "Mananatili ang strike. Buksan ang RepLiT para makita ang sagot.",
        )
    return (
        "Appeal not accepted",
        "The strike stays. Open RepLiT to read the answer.",
    )


def verified_by(language: Language, team: str) -> str:
    """The verified body naming the team that verified it — never the person."""
    if language == "tl":
        return f"Na-verify ng {team} ang fire report mo. May mga responder nang ipinapadala."
    return f"Your fire report was verified by {team}. Responders are being assigned."


# The National ID review's answer (app/services/national_id.py).
NATIONAL_ID_APPROVED: dict[Language, tuple[str, str]] = {
    "en": (
        "National ID verified",
        "Your verification went up. Your photos have been deleted.",
    ),
    "tl": (
        "Na-verify ang National ID mo",
        "Tumaas na ang verification mo. Binura na ang mga litrato mo.",
    ),
}
NATIONAL_ID_RETRY: dict[Language, tuple[str, str]] = {
    "en": (
        "Try your National ID again",
        "It was not accepted. Send new photos from the app.",
    ),
    "tl": (
        "Subukan ulit ang National ID mo",
        "Hindi ito tinanggap. Magpadala ng bagong litrato mula sa app.",
    ),
}

# Profile's "Send a test alert" (app/api/routes/devices.py).
TEST_ALERT: dict[Language, tuple[str, str]] = {
    "en": ("RepLiT test", "Push notifications are working."),
    "tl": ("Test ng RepLiT", "Gumagana ang mga notification."),
}
