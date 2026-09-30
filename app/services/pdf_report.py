"""Fire-out PDF report generation with reportlab (Phase 14).

Renders the structured incident facts (from app.services.ai_summary) plus the
latest AI narrative into a one-page incident report. Pure/sync — build the bytes
and hand them to a Response.

It reads the facts as gather_incident_facts builds them. It used to read a
"dispatched_resources" list and v10 timestamp names that the facts stopped
carrying in v11, so the endpoint failed on every real incident; who went now
comes from the team captain's Post-Incident Report, as it does for the summary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _esc(text: str) -> str:
    """Escape the reportlab Paragraph markup characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kv_table(rows: list[list[str]]) -> Any:
    """A two-column key/value table."""
    table = Table(rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _grid_table(rows: list[list[str]]) -> Any:
    """A bordered table with a header row."""
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D32F2F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_fire_out_pdf(facts: dict[str, Any], summary_text: str | None) -> bytes:
    """Build a one-page incident report PDF and return its bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Fire Incident Report - {facts['designation']}",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    flow: list[Any] = []

    flow.append(Paragraph("RepLiT Fire Incident Report", styles["Title"]))
    flow.append(
        Paragraph(
            _esc(f"{facts['designation']} - status: {facts['status']}"),
            styles["Heading3"],
        )
    )
    flow.append(Spacer(1, 5 * mm))

    flow.append(
        _kv_table(
            [
                ["Designation", str(facts["designation"])],
                ["Status", str(facts["status"])],
                ["Centroid", f"{facts['centroid']['lat']}, {facts['centroid']['lng']}"],
                [
                    "Confidence",
                    f"{facts['confidence']['score']} ({facts['confidence']['band']})",
                ],
                ["Citizen reports", str(facts["report_count"])],
                ["Alarm level", str(facts["alarm_level"] or "none")],
            ]
        )
    )
    flow.append(Spacer(1, 5 * mm))

    flow.append(Paragraph("Lifecycle Timeline", styles["Heading2"]))
    ts = facts["timestamps"]
    timeline = [
        ("Reported", "reported_at"),
        ("Accepted", "accepted_at"),
        ("En route", "en_route_at"),
        ("On scene", "arrived_at"),
        ("Fire out", "fire_out_at"),
        ("Report filed", "closed_at"),
    ]
    # Only incidents that ran under v10 have a dispatch time.
    if ts.get("dispatched_at"):
        timeline.insert(2, ("Dispatched", "dispatched_at"))
    flow.append(_kv_table([[label, str(ts.get(key) or "-")] for label, key in timeline]))
    flow.append(Spacer(1, 5 * mm))

    nb = facts["neighborhood"]
    flow.append(Paragraph("Neighborhood Corroboration", styles["Heading2"]))
    flow.append(
        Paragraph(
            f"{nb['alerted']} alerted, {nb['responded']} responded, "
            f"{nb['confirmed']} confirmed a fire",
            styles["BodyText"],
        )
    )
    flow.append(Spacer(1, 5 * mm))

    flow.append(Paragraph("Post-Incident Report", styles["Heading2"]))
    report = facts.get("post_incident_report")
    if report:
        units = ", ".join(
            f"{u['name']} ({u['type']})" if u.get("type") else str(u["name"])
            for u in report.get("units") or []
        )
        crew = ", ".join(str(m["name"]) for m in report.get("roster") or [])
        rows = [
            ["Filed by", str(report.get("filed_by") or "-")],
            ["Time of the incident", str(report.get("incident_at") or "-")],
            ["Time the fire was out", str(report.get("fire_out_at") or "-")],
            ["Units", units or "-"],
            ["Driver", str(report.get("driver_name") or "-")],
            ["Roster", crew or "-"],
            ["Equipment taken", ", ".join(report.get("equipment_taken") or []) or "-"],
        ]
        if report.get("false_alarm"):
            rows.append(["False alarm", str(report.get("false_alarm_note") or "Yes")])
        flow.append(_kv_table([[k, Paragraph(_esc(v), styles["BodyText"])] for k, v in rows]))
    else:
        flow.append(Paragraph("Not filed yet.", styles["BodyText"]))
    flow.append(Spacer(1, 5 * mm))

    flow.append(Paragraph("Fire Codes Activated", styles["Heading2"]))
    codes = facts["fire_codes"]
    if codes:
        rows = [["Code", "Name", "Pressed at"]]
        rows.extend(
            [str(c["code"]), str(c["name"]), str(c["pressed_at"] or "-")] for c in codes
        )
        flow.append(_grid_table(rows))
    else:
        flow.append(Paragraph("None.", styles["BodyText"]))

    if summary_text:
        flow.append(Spacer(1, 5 * mm))
        flow.append(Paragraph("AI Summary", styles["Heading2"]))
        for para in summary_text.split("\n\n"):
            cleaned = para.replace("\n", " ").strip()
            if cleaned:
                flow.append(Paragraph(_esc(cleaned), styles["BodyText"]))

    flow.append(Spacer(1, 8 * mm))
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    flow.append(Paragraph(_esc(f"Generated {generated} - RepLiT"), styles["Italic"]))

    doc.build(flow)
    return buffer.getvalue()