"""Figure for Master Context / thesis Section 3.3.3 — Network and Architecture.

Draws the four-layer architecture as a print-ready figure and writes SVG, PDF and
300 dpi PNG. Designed at 6.5 in wide — a thesis page's usable width — so the point
sizes in the drawing are the point sizes on the printed page. Scaling the figure in
Word shrinks the labels with it, so insert it at 100%.

Two details differ from an earlier draft of the prose, deliberately:
  * 23 route modules, not 24 (app/api/routes, excluding __init__).
  * Mapbox is reached by the clients themselves, so it sits on the presentation
    layer. Nothing about the basemap passes through the API.

Run:  uv run --no-cache --with matplotlib python docs/figures/architecture_figure.py
"""

from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

# Print-friendly: the structure reads in black and white, one accent for emphasis.
INK = "#18181B"
MID = "#52525B"
SOFT = "#71717A"
LINE = "#3F3F46"
HAIR = "#A1A1AA"
ACCENT = "#9A3412"
BAND_A = "#F4F4F5"
BAND_B = "#EBEBED"

TITLE_PT = 7.6
SUB_PT = 6.0
CHIP_PT = 6.2
ARROW_PT = 6.2
FOOT_PT = 5.6

fig, ax = plt.subplots(figsize=(6.5, 8.0))
ax.set_xlim(0, 100)
ax.set_ylim(-9, 100)
ax.axis("off")


def band(y0: float, y1: float, label: str, fill: str) -> None:
    """A full-width layer band with its name in the left gutter."""
    ax.add_patch(Rectangle((0, y0), 100, y1 - y0, facecolor=fill, edgecolor="none", zorder=0))
    ax.text(
        2.6, (y0 + y1) / 2, label.upper(), rotation=90, ha="center", va="center",
        fontsize=7.2, fontweight="bold", color=ACCENT, zorder=2,
    )


def box(
    x0: float, y0: float, x1: float, y1: float, title: str, body: str = "",
    *, dashed: bool = False, fill: str = "#FFFFFF", lw: float = 0.9,
    title_pt: float = TITLE_PT, edge: str = LINE,
) -> None:
    """A titled container: the title always sits at the top, contents below it."""
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0,
            boxstyle="round,pad=0,rounding_size=1.2",
            facecolor=fill, edgecolor=edge, linewidth=lw,
            linestyle=(0, (2.4, 1.6)) if dashed else "solid", zorder=2,
        )
    )
    cx = (x0 + x1) / 2
    ax.text(cx, y1 - 2.7, title, ha="center", va="center",
            fontsize=title_pt, fontweight="bold", color=INK, zorder=3)
    if body:
        ax.text(cx, y1 - 5.3, body, ha="center", va="top",
                fontsize=SUB_PT, color=MID, linespacing=1.5, zorder=3)


def chip(x0: float, y0: float, x1: float, y1: float, text: str) -> None:
    """A small labelled tile for one responsibility."""
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0,
            boxstyle="round,pad=0,rounding_size=0.9",
            facecolor="#FAFAFA", edgecolor=HAIR, linewidth=0.65, zorder=3,
        )
    )
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=CHIP_PT, color=INK, linespacing=1.3, zorder=4)


def chip_row(x0: float, x1: float, y0: float, y1: float, labels: list[str], gap: float = 1.6) -> None:
    """Equal-width chips spanning x0..x1."""
    w = (x1 - x0 - gap * (len(labels) - 1)) / len(labels)
    for i, text in enumerate(labels):
        left = x0 + i * (w + gap)
        chip(left, y0, left + w, y1, text)


def down_arrow(x: float, y_from: float, y_to: float, *, lw: float = 1.1, dashed: bool = False) -> None:
    ax.add_patch(
        FancyArrowPatch(
            (x, y_from), (x, y_to),
            arrowstyle="-|>", mutation_scale=9, linewidth=lw,
            color=SOFT if dashed else ACCENT,
            linestyle=(0, (2.6, 1.8)) if dashed else "solid",
            shrinkA=0, shrinkB=0, zorder=5,
        )
    )


def note(x: float, y: float, text: str, *, ha: str = "left", style: str = "italic",
         color: str = MID, pt: float = ARROW_PT, rotation: float = 0) -> None:
    ax.text(x, y, text, ha=ha, va="center", fontsize=pt, color=color,
            style=style, rotation=rotation, linespacing=1.4, zorder=6)


# ── Bands ────────────────────────────────────────────────────────────────────
band(77, 99, "Presentation", BAND_A)
band(47.5, 70.5, "Business", BAND_B)
band(24, 41, "Data", BAND_A)
band(0, 17.5, "Infrastructure", BAND_B)

# ── Presentation layer ───────────────────────────────────────────────────────
box(7, 79.5, 29, 97, "Flutter mobile app",
    "Citizens · Response Teams\nFire Volunteer and BFP\nteam captains\n\nSOS hold · camera · GPS",
    title_pt=7.2)
box(31, 79.5, 53, 97, "Admin Console",
    "Admin\nReact 18 · Vite\n\nAccept and route\nincidents · governance",
    title_pt=7.2)
box(55, 79.5, 77, 97, "Observer Console",
    "Police · Medical\nBarangay team captains\nReact 18 · Vite\n\nWatch · Accept",
    title_pt=7.2)
box(80, 79.5, 98, 97, "Mapbox basemap",
    "Raster tiles,\nfetched by each\nclient directly",
    dashed=True, fill="#FBFAF9", edge=SOFT, title_pt=7.2)

# Shared basemap connection: a dashed bus above the row, touching all four cards.
ax.plot([18, 89], [98.2, 98.2], linestyle=(0, (2.6, 1.8)), linewidth=0.7, color=SOFT, zorder=4)
for x in (18, 42, 66, 89):
    ax.plot([x, x], [97, 98.2], linestyle=(0, (2.6, 1.8)), linewidth=0.7, color=SOFT, zorder=4)

# Presentation → Business
for x in (18, 66):
    down_arrow(x, 79.5, 70.9, lw=0.8)
down_arrow(42, 79.5, 70.9, lw=1.3)
note(69, 76.4, "HTTPS · JSON · JWT bearer")
note(69, 73.6, "the API is the only way in", color=SOFT, pt=5.9)

# ── Business layer ───────────────────────────────────────────────────────────
box(7, 48.5, 98, 69.5, "FastAPI application", title_pt=8.0)

chip(10, 59.5, 60, 64.5, "REST API — 120 endpoints across 23 modules")
chip(62, 59.5, 95, 64.5, "Realtime channel (WebSocket)")

chip_row(10, 95, 53, 58.5, [
    "Clustering", "Verification", "Notification",
    "Incident\nlifecycle", "Summarisation", "Audit",
])

ax.add_patch(
    FancyBboxPatch(
        (10, 49.3), 85, 3.2,
        boxstyle="round,pad=0,rounding_size=0.9",
        facecolor="#FDF6F1", edgecolor="#E7C9B6", linewidth=0.65, zorder=3,
    )
)
ax.text(52.5, 50.9,
        "JWT validation  ·  authority enforcement (user_role × agency_type)  ·  request routing",
        ha="center", va="center", fontsize=CHIP_PT, color=ACCENT, zorder=4)

# Business → Data
down_arrow(39, 48.5, 24.4, lw=1.3)
note(42, 44.4, "in-process calls, Pydantic-validated models")

# Business → external managed services, bypassing the data layer.
down_arrow(86, 48.5, 17.9, dashed=True, lw=0.9)
note(87.6, 33, "server-side HTTPS", color=SOFT, pt=5.7, rotation=90, ha="center")

# ── Data layer ───────────────────────────────────────────────────────────────
box(7, 25, 70, 40, "Data access layer", title_pt=7.8)
chip_row(10, 67, 31.3, 35.5, ["asyncpg\nconnection pool", "Pydantic v2\nvalidation", "Centroid ·\nhaversine"])
chip_row(10, 67, 26.3, 30.5, ["PostGIS proximity\n(300 m radius)", "Overlap\ndetection", "Confidence\n0.4N + 0.3S + 0.3V"])

# Data → Supabase
down_arrow(39, 25, 17.9, lw=1.3)
note(42, 21.2, "asyncpg over TLS · service role")

# ── Infrastructure layer ─────────────────────────────────────────────────────
box(7, 1, 70, 16.5, "Supabase (managed)", title_pt=7.8)
chip_row(10, 67, 7.9, 12.0, ["PostgreSQL 17.6\n+ PostGIS 3.3.7", "GoTrue\nauthentication"])
chip_row(10, 67, 3.6, 7.7, ["Storage —\nprivate buckets", "Realtime\nchannels"])
ax.text(38.5, 2.1, "Row-level security on all 30 tables; authority reinforced by database triggers",
        ha="center", va="center", fontsize=5.6, color=SOFT, style="italic", zorder=4)

box(74, 1, 98, 16.5, "External services", title_pt=7.2,
    dashed=True, fill="#FBFAF9", edge=SOFT)
ax.text(86, 7.1,
        "Firebase FCM — push\nTwilio — SMS OTP\nBrevo — email\nAnthropic — summaries\nDidit — KYC review",
        ha="center", va="center", fontsize=SUB_PT, color=MID, linespacing=1.7, zorder=4)

# ── Footnotes ────────────────────────────────────────────────────────────────
note(0, -3.2,
     "Solid arrows are calls inside the system; dashed arrows and dashed borders are direct HTTPS to a third party.",
     color=SOFT, pt=FOOT_PT, style="normal")
note(0, -5.6,
     "Each layer depends only on the one beneath it. The FastAPI application holds the sole database credential,",
     color=SOFT, pt=FOOT_PT, style="normal")
note(0, -7.4,
     "so no client reaches Supabase directly.",
     color=SOFT, pt=FOOT_PT, style="normal")

out = pathlib.Path(__file__).parent
stem = "fig-3-3-3-architecture"
fig.savefig(out / f"{stem}.svg", format="svg", bbox_inches="tight", pad_inches=0.06)
fig.savefig(out / f"{stem}.pdf", format="pdf", bbox_inches="tight", pad_inches=0.06)
fig.savefig(out / f"{stem}.png", format="png", dpi=300, bbox_inches="tight",
            pad_inches=0.06, facecolor="white")
print("wrote:", ", ".join(sorted(p.name for p in out.glob(f"{stem}.*"))))
