"""v1.12.48: the console's fire pulse moves in production.

react-leaflet applies ``pathOptions`` with setStyle after Leaflet has created
the path, and Leaflet reads ``className`` only as it creates it. A class in
there works on the Vite dev server (StrictMode mounts twice) and never in a
production build, which is how the v1.12.46 ripple shipped still.
"""

from __future__ import annotations

import re
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[1] / "admin-web" / "src"
MAPS = ("pages/LiveMapPage.jsx", "pages/MapManagement.jsx", "components/incidents/AreaMap.jsx")


def test_no_map_path_takes_its_class_through_path_options() -> None:
    offending = [
        str(path.relative_to(CONSOLE))
        for path in CONSOLE.rglob("*.jsx")
        if re.search(r"pathOptions=\{\{[^}]*\bclassName\b", path.read_text(encoding="utf-8"))
    ]
    assert offending == []


def test_every_map_with_fires_draws_the_one_pulse() -> None:
    pulse = (CONSOLE / "map" / "FirePulse.jsx").read_text(encoding="utf-8")
    assert 'className="rpl-ripple"' in pulse
    assert 'className="rpl-halo"' in pulse
    for name in MAPS:
        assert "<FirePulse" in (CONSOLE / name).read_text(encoding="utf-8"), name
