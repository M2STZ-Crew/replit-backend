"""What staff alerts say, in the language each chose (Tagalog everywhere, 1.3).

Staff read RepLiT in English or in Tagalog at CEFR B1 like residents do
(users.language, set by the app and the Admin console with
PUT /auth/me/language), and their pushes and inbox rows follow it: a new
fire, the reminders until a coordinator acknowledges it, a dispatch, an
incident routed to the team, an alarm request and BFP's answer to it.

Alarm levels keep BFP's own words ("2nd alarm") in both languages, the way
they are said on the radio, and so do Area names ("Area 1.2"). Tagalog here
is the app's: everyday Metro Manila Tagalog in short sentences, keeping the
English words staff use anyway (report, responder, dispatch, team).
"""

from __future__ import annotations

from app.services.citizen_copy import Language


def area_called(designation: str | None, language: Language, *, start: bool = False) -> str:
    """ "Area 1.2" for a designation (older rows already carry the word), else
    "an incident" in the language — capitalised when it starts the sentence."""
    text = (designation or "").strip()
    if text:
        return text if text.lower().startswith("area") else f"Area {text}"
    if language == "tl":
        return "Ang insidente" if start else "isang insidente"
    return "The incident" if start else "an incident"


def new_fire(language: Language, designation: str | None) -> tuple[str, str]:
    """A resident's fire report, to the staff who can see it."""
    if language == "tl":
        return (
            f"May ini-report na sunog: {designation or 'bagong insidente'}",
            "May residenteng nag-report ng sunog. I-tap para buksan, i-verify at tugunan ito.",
        )
    return (
        f"Fire reported: {designation or 'new incident'}",
        "A resident reported a fire. Tap to open it, verify it and respond.",
    )


def reminder(language: Language, designation: str | None) -> tuple[str, str]:
    """A coordinator's reminder, until they acknowledge the fire."""
    title = new_fire(language, designation)[0]
    if language == "tl":
        return title, "Hinihintay ka pa. I-tap para buksan at i-acknowledge ito."
    return title, "Still waiting for you. Tap to open it and acknowledge."


def dispatched(
    language: Language,
    designation: str | None,
    crew_role: str | None = None,
    vehicle_name: str | None = None,
) -> tuple[str, str]:
    """A responder's dispatch: where, and as what, on which vehicle."""
    parts: list[str] = []
    if crew_role:
        parts.append(crew_role)
    if language == "tl":
        if vehicle_name:
            parts.append(f"sakay ng {vehicle_name}")
        suffix = f" — {' '.join(parts)}" if parts else ""
        return "Na-dispatch ka", f"Tumugon sa {designation or 'isang insidente'}{suffix}."
    if vehicle_name:
        parts.append(f"on {vehicle_name}")
    suffix = f" — {' '.join(parts)}" if parts else ""
    return "You've been dispatched", f"Respond to {designation or 'an incident'}{suffix}."


def routed(language: Language, designation: str | None) -> tuple[str, str]:
    """An incident Admin routed to a team, to its captains."""
    if language == "tl":
        return (
            "May insidenteng ipinasa sa team mo",
            f"Ipinasa ng Admin ang {designation or 'isang insidente'} sa team mo. "
            "Buksan ito para tumugon.",
        )
    return (
        "Incident routed to your team",
        f"Admin routed {designation or 'an incident'} to your team. Open it to respond.",
    )


def alarm_requested(
    language: Language,
    requester: str | None,
    organization: str | None,
    level: str,
    designation: str | None,
) -> tuple[str, str]:
    """A request to raise the alarm, to BFP's coordinators. [level] is BFP's
    own label ("2nd alarm")."""
    area = area_called(designation, language)
    who = f"{requester} ({organization})" if requester and organization else requester
    if language == "tl":
        if who:
            body = f"Humiling si {who} ng {level} para sa {area}."
        else:
            org = f" ({organization})" if organization else ""
            body = f"Humiling ang isang responder{org} ng {level} para sa {area}."
        return "May hiling na itaas ang alarma", body
    if not who:
        who = f"A responder ({organization})" if organization else "A responder"
    return "Alarm escalation requested", f"{who} asked for {level} on {area}."


def alarm_answered(
    language: Language,
    approved: bool,
    level: str,
    designation: str | None,
    notes: str | None = None,
) -> tuple[str, str]:
    """BFP's answer, to whoever asked. Review notes are added as BFP wrote them."""
    area = area_called(designation, language, start=True)
    if language == "tl":
        if approved:
            return (
                "Itinaas ng BFP ang alarma",
                f"Nasa {level} na ang {_lower(area)}, gaya ng hiniling mo.",
            )
        title, body = (
            "Hindi inaprubahan ng BFP ang hiling mong alarma",
            f"Walang babaguhin sa {_lower(area)}.",
        )
    else:
        if approved:
            return "BFP raised the alarm", f"{area} is now at {level}, as you asked."
        title, body = "BFP declined your alarm request", f"{area} stays as it is."
    return title, f"{body} {notes}" if notes else body


def _lower(area: str) -> str:
    """ "ang insidente" mid-sentence; Area names keep their capital."""
    return "insidente" if area == "Ang insidente" else area
