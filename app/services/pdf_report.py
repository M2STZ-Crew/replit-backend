"""The incident report PDF, built with reportlab (Phase 14).

Renders the structured incident facts (from app.services.ai_summary) and the
latest AI summary as a report a fire coordinator or the BFP could file:

    title block and key facts
    1. Summary                  the AI narrative, labelled as such
    2. Incident details         location, alarm level, citizen reports
    3. Response timeline        reported -> accepted -> ... -> report filed
    4. Verification             who accepted it, and who joined
    5. Post-Incident Reports    one subsection per responding team's report
    6. Fire codes activated

Every responding team files its own Post-Incident Report, so section 5 lists
them all, in the order they were filed. Times are printed in Philippine time -
the facts hold UTC, which reads eight hours off to anyone who was at the fire.

Pure and synchronous: build the bytes and hand them to a Response. It reads the
facts exactly as gather_incident_facts builds them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.ai_summary import ph_time

_ACCENT = colors.HexColor("#C8400A")
_INK = colors.HexColor("#1A1A1A")
_MUTED = colors.HexColor("#666666")
_RULE = colors.HexColor("#D9D4CE")
_BAND = colors.HexColor("#F4F0EB")
_WARN = colors.HexColor("#9A3412")

_MARGIN = 18 * mm
# SimpleDocTemplate's frame pads its content 6pt a side. Tables are sized to the
# width paragraphs actually get, so headings and table edges line up.
_PAD = 6
_WIDTH = A4[0] - 2 * _MARGIN - 2 * _PAD

_AGENCY = {
    "fire_volunteer": "Fire Volunteers",
    "bfp": "Bureau of Fire Protection",
    "police": "Police",
    "medical": "Medical",
    "barangay": "Barangay",
}

_STATUS = {
    "reported": "Reported",
    "verified": "Verified",
    "en_route": "Responders on the way",
    "arrived": "Responders on scene",
    "fire_out": "Fire out",
    "post_incident_report": "Fire out - report due",
    "closed": "Closed",
    "rejected": "Not confirmed",
    "merged": "Merged into another incident",
}


def _esc(text: object) -> str:
    """Escape the reportlab Paragraph markup characters."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _label(value: str | None) -> str:
    """'first_alarm' -> 'First alarm'."""
    if not value:
        return "None"
    return value.replace("_", " ").capitalize()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    body = ParagraphStyle(
        "body", parent=base, fontName="Helvetica", fontSize=9.5, leading=14, textColor=_INK
    )
    return {
        "body": body,
        "eyebrow": ParagraphStyle(
            "eyebrow", parent=body, fontName="Helvetica-Bold", fontSize=8, leading=10,
            textColor=_ACCENT,
        ),
        "title": ParagraphStyle(
            "title", parent=body, fontName="Helvetica-Bold", fontSize=22, leading=26
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontSize=12, leading=16, textColor=_MUTED
        ),
        "h2": ParagraphStyle(
            "h2", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=16,
            spaceBefore=4, spaceAfter=4,
        ),
        "h3": ParagraphStyle(
            "h3", parent=body, fontName="Helvetica-Bold", fontSize=10.5, leading=14
        ),
        "muted": ParagraphStyle(
            "muted", parent=body, fontSize=8.5, leading=12, textColor=_MUTED
        ),
        "key": ParagraphStyle(
            "key", parent=body, fontSize=8.5, leading=12, textColor=_MUTED
        ),
        "cell": ParagraphStyle("cell", parent=body, fontSize=9.5, leading=13),
        "head": ParagraphStyle(
            "head", parent=body, fontName="Helvetica-Bold", fontSize=8.5, leading=11,
            textColor=_MUTED,
        ),
        "warn": ParagraphStyle(
            "warn", parent=body, fontName="Helvetica-Bold", fontSize=9.5, leading=13,
            textColor=_WARN,
        ),
        "right": ParagraphStyle(
            "right", parent=body, fontSize=8.5, leading=12, textColor=_MUTED,
            alignment=TA_RIGHT,
        ),
    }


def _kv_table(rows: list[tuple[str, Any]], st: dict[str, ParagraphStyle]) -> Table:
    """Label on the left, value on the right, a hairline under each row."""
    data = [
        [
            Paragraph(_esc(key), st["key"]),
            value if not isinstance(value, str) else Paragraph(_esc(value), st["cell"]),
        ]
        for key, value in rows
    ]
    table = Table(data, colWidths=[44 * mm, _WIDTH - 44 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
            ]
        )
    )
    return table


def _grid_table(
    header: list[str], rows: list[list[str]], widths: list[float], st: dict[str, ParagraphStyle]
) -> Table:
    """A ruled table with a shaded header row that repeats across pages."""
    data = [[Paragraph(_esc(h), st["head"]) for h in header]]
    data += [[Paragraph(_esc(cell), st["cell"]) for cell in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BAND),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
                ("LINEABOVE", (0, 0), (-1, 0), 0.4, _RULE),
            ]
        )
    )
    return table


def _section(*parts: Any) -> KeepTogether:
    """A heading and its table on one page, so neither is left behind by a break."""
    return KeepTogether(list(parts))


def _key_facts(facts: dict[str, Any], st: dict[str, ParagraphStyle]) -> Table:
    """The four facts a reader looks for first, in a shaded band under the title."""
    ts = facts["timestamps"]
    reports = facts.get("post_incident_reports") or []
    cells = [
        ("STATUS", _STATUS.get(str(facts["status"]), _label(str(facts["status"])))),
        ("REPORTED", ph_time(ts.get("reported_at"))),
        ("FIRE OUT", ph_time(ts.get("fire_out_at"))),
        ("TEAM REPORTS FILED", str(len(reports))),
    ]
    data = [
        [Paragraph(label, st["head"]) for label, _ in cells],
        [Paragraph(_esc(value), st["h3"]) for _, value in cells],
    ]
    table = Table(data, colWidths=[_WIDTH / 4] * 4, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _BAND),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 1),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _team_report(
    report: dict[str, Any], number: int, st: dict[str, ParagraphStyle]
) -> list[Any]:
    """One team's Post-Incident Report: a heading, who filed it, and what they picked."""
    team = report.get("organization") or "Team with no organisation on record"
    agency = _AGENCY.get(str(report.get("filed_by_agency") or ""), "")
    units = ", ".join(
        f"{u['name']} ({u['type']})" if u.get("type") else str(u["name"])
        for u in report.get("units") or []
    )
    roster = report.get("roster") or []
    crew = ", ".join(
        f"{m['name']} ({m['role']})" if m.get("role") else str(m["name"]) for m in roster
    )
    rows: list[tuple[str, Any]] = [
        ("Time of the incident", ph_time(report.get("incident_at"))),
        ("Time the fire was out", ph_time(report.get("fire_out_at"))),
        ("Units", units or "-"),
        ("Driver", str(report.get("driver_name") or "-")),
        (f"Roster ({len(roster)})", crew or "-"),
        ("Equipment taken", ", ".join(report.get("equipment_taken") or []) or "-"),
    ]
    if report.get("notes"):
        rows.append(("Notes", str(report["notes"])))
    if report.get("false_alarm"):
        rows.insert(
            0,
            (
                "False alarm",
                Paragraph(_esc(report.get("false_alarm_note") or "Yes"), st["warn"]),
            ),
        )
    filed = (
        f"Filed by {report.get('filed_by') or 'the team captain'} "
        f"on {ph_time(report.get('submitted_at'))}"
    )
    # "Bureau of Fire Protection - Pasay ..." already says whose team it is.
    named = agency and agency.lower() not in str(team).lower()
    heading = f"5.{number}  {team}" + (f" - {agency}" if named else "")
    return [
        KeepTogether(
            [
                Paragraph(_esc(heading), st["h3"]),
                Paragraph(_esc(filed), st["muted"]),
                Spacer(1, 2 * mm),
                _kv_table(rows, st),
            ]
        ),
        Spacer(1, 5 * mm),
    ]


def build_fire_out_pdf(
    facts: dict[str, Any],
    summary_text: str | None,
    *,
    summary_model: str | None = None,
    compress: bool = True,
) -> bytes:
    """Build the incident report PDF and return its bytes.

    ``compress=False`` leaves the page text readable in the bytes, which is how
    the tests check what the report actually says.
    """
    st = _styles()
    designation = str(facts["designation"])
    generated = ph_time(datetime.now(UTC))

    def _page(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(_MARGIN + _PAD, 14 * mm, A4[0] - _MARGIN - _PAD, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            _MARGIN + _PAD,
            9.5 * mm,
            f"RepLiT Fire Incident Report - {designation} - generated {generated}",
        )
        canvas.drawRightString(A4[0] - _MARGIN - _PAD, 9.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Fire Incident Report - {designation}",
        author="RepLiT",
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        pageCompression=1 if compress else 0,
    )
    flow: list[Any] = []

    # ------------------------------------------------------------ title ---
    flow.append(Paragraph("REPLIT - BARANGAY 76, PASAY CITY", st["eyebrow"]))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(Paragraph("Fire Incident Report", st["title"]))
    flow.append(Paragraph(_esc(designation), st["subtitle"]))
    flow.append(Spacer(1, 3 * mm))
    flow.append(HRFlowable(width="100%", thickness=1.2, color=_ACCENT, spaceAfter=4 * mm))
    flow.append(_key_facts(facts, st))
    flow.append(Spacer(1, 6 * mm))

    # ---------------------------------------------------------- 1 summary ---
    flow.append(Paragraph("1. Summary", st["h2"]))
    if summary_text and summary_text.strip():
        for para in summary_text.split("\n\n"):
            cleaned = para.replace("\n", " ").strip()
            if cleaned:
                flow.append(Paragraph(_esc(cleaned), st["body"]))
                flow.append(Spacer(1, 2 * mm))
        by = f" ({summary_model})" if summary_model else ""
        flow.append(
            Paragraph(
                _esc(f"Written by AI{by} from the records in sections 2 to 6 of this report."),
                st["muted"],
            )
        )
    else:
        flow.append(
            Paragraph(
                "No summary has been written yet. One is written automatically each time a "
                "team files its Post-Incident Report.",
                st["muted"],
            )
        )
    flow.append(Spacer(1, 6 * mm))

    # ---------------------------------------------------------- 2 details ---
    nb = facts["neighborhood"]
    confidence = facts["confidence"]
    score = confidence.get("score")
    flow.append(
        _section(
            Paragraph("2. Incident details", st["h2"]),
            _kv_table(
            [
                ("Incident", designation),
                ("Location", f"{facts['centroid']['lat']}, {facts['centroid']['lng']} (lat, lng)"),
                ("Alarm level", _label(facts.get("alarm_level"))),
                ("Citizen reports", str(facts["report_count"])),
                (
                    "Confidence",
                    "-" if score is None
                    else f"{round(float(score) * 100)}% ({_label(confidence.get('band'))})",
                ),
                (
                    "Neighbours asked",
                    f"{nb['alerted']} alerted, {nb['responded']} answered, "
                    f"{nb['confirmed']} confirmed a fire",
                ),
            ],
            st,
            ),
        )
    )
    flow.append(Spacer(1, 6 * mm))

    # --------------------------------------------------------- 3 timeline ---
    ts = facts["timestamps"]
    steps = [
        ("Reported", "reported_at"),
        ("Accepted (verified)", "accepted_at"),
        ("Responders on the way", "en_route_at"),
        ("Responders on scene", "arrived_at"),
        ("Fire out", "fire_out_at"),
        ("First report filed, incident closed", "closed_at"),
    ]
    # Only incidents that ran under v10 have a dispatch time.
    if ts.get("dispatched_at"):
        steps.insert(2, ("Dispatched", "dispatched_at"))
    flow.append(
        _section(
            Paragraph("3. Response timeline", st["h2"]),
            _grid_table(
                ["Step", "Time (Philippine time)"],
                [[label, ph_time(ts.get(key), missing="Not recorded")] for label, key in steps],
                [_WIDTH * 0.55, _WIDTH * 0.45],
                st,
            ),
        )
    )
    flow.append(Spacer(1, 6 * mm))

    # ----------------------------------------------------- 4 verification ---
    acceptances = facts.get("acceptances") or []
    if acceptances:
        flow.append(
            _section(
                Paragraph("4. Verification", st["h2"]),
                _grid_table(
                ["Agency", "Team", "Part played", "Time"],
                [
                    [
                        _AGENCY.get(str(a.get("agency") or ""), "Admin"),
                        str(a.get("organization") or "-"),
                        "Verified the incident" if a.get("is_first") else "Also took part",
                        ph_time(a.get("accepted_at")),
                    ]
                    for a in acceptances
                ],
                [_WIDTH * 0.24, _WIDTH * 0.30, _WIDTH * 0.22, _WIDTH * 0.24],
                st,
                ),
            )
        )
    else:
        flow.append(
            _section(
                Paragraph("4. Verification", st["h2"]),
                Paragraph("No verification is on record.", st["muted"]),
            )
        )
    flow.append(Spacer(1, 6 * mm))

    # ------------------------------------------- 5 post-incident reports ---
    reports = facts.get("post_incident_reports") or []
    flow.append(Paragraph("5. Post-Incident Reports", st["h2"]))
    if reports:
        flow.append(
            Paragraph(
                _esc(
                    f"{len(reports)} responding team{'s' if len(reports) != 1 else ''} filed "
                    "a report, listed in the order they were filed. Each captain picked the "
                    "units, driver, roster and equipment from their own organisation."
                ),
                st["muted"],
            )
        )
        flow.append(Spacer(1, 4 * mm))
        for number, report in enumerate(reports, start=1):
            flow += _team_report(report, number, st)
    else:
        flow.append(
            Paragraph("No team has filed its Post-Incident Report yet.", st["muted"])
        )
        flow.append(Spacer(1, 5 * mm))
    flow.append(Spacer(1, 1 * mm))

    # ------------------------------------------------------- 6 fire codes ---
    codes = facts.get("fire_codes") or []
    flow.append(
        _section(
            Paragraph("6. Fire codes activated", st["h2"]),
            _grid_table(
                ["Code", "Meaning", "Pressed at"],
                [
                    [str(c["code"]), str(c["name"]), ph_time(c.get("pressed_at"))]
                    for c in codes
                ],
                [_WIDTH * 0.16, _WIDTH * 0.50, _WIDTH * 0.34],
                st,
            )
            if codes
            else Paragraph("None.", st["muted"]),
        )
    )

    doc.build(flow, onFirstPage=_page, onLaterPages=_page)
    return buffer.getvalue()
