"""Fire-out PDF report generation with reportlab (Phase 14).

Renders the structured incident facts (from app.services.ai_summary) plus the
latest AI narrative into a one-page incident report. Pure/sync — build the bytes
and hand them to a Response.
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
        ("Verified", "verified_at"),
        ("Dispatched", "dispatched_at"),
        ("En route", "en_route_at"),
        ("Arrived", "arrived_at"),
        ("Resolved", "resolved_at"),
        ("Rejected", "rejected_at"),
    ]
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

    flow.append(Paragraph("Dispatched Resources", styles["Heading2"]))
    resources = facts["dispatched_resources"]
    if resources:
        rows = [["Responder", "Organization", "Type", "Status"]]
        rows.extend(
            [
                str(d["responder"] or "-"),
                str(d["organization"] or "-"),
                str(d["type"]),
                str(d["status"]),
            ]
            for d in resources
        )
        flow.append(_grid_table(rows))
    else:
        flow.append(Paragraph("None recorded.", styles["BodyText"]))
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