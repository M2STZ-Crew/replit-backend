"""Backend v1.12.28 (12 Nov 2026): the APK download site and the console's domain.

- The console's own addresses — its Vercel project and the
  reportwhatslit-admin domain it moves to — are always allowed by CORS, so
  the move needs no edit on Render.
- apk-web/ is the download page (reportwhatslit-apk.vercel.app): it reads the
  newest release from the app repository, so a new version needs no edit.
- The console's /installation goes to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import CONSOLE_ORIGINS, Settings

ROOT = Path(__file__).resolve().parents[1]


def test_the_console_is_allowed_from_its_old_and_new_addresses() -> None:
    settings = Settings(cors_origins="http://localhost:5173")
    assert settings.cors_origins_list == [
        "http://localhost:5173",
        "https://reportwhatslit.vercel.app",
        "https://reportwhatslit-admin.vercel.app",
        "https://replit-backend-5u9u.vercel.app",
    ]
    # Named in the environment too: not listed twice.
    both = Settings(cors_origins=",".join(CONSOLE_ORIGINS))
    assert both.cors_origins_list == list(CONSOLE_ORIGINS)


def test_the_download_page_reads_the_newest_release() -> None:
    page = (ROOT / "apk-web" / "index.html").read_text(encoding="utf-8")
    assert "https://api.github.com/repos/${REPO}/releases/latest" in page
    assert "const REPO = 'M2STZ-Crew/replit-android';" in page
    assert "New for testers" in page
    # Self-contained: the font and the mark are its own.
    for asset in ("fonts/inter-v20-latin-wght.woff2", "assets/logo-mark.png"):
        assert (ROOT / "apk-web" / asset).is_file(), asset
    # Dark and light, as the design system draws them.
    assert "@media (prefers-color-scheme: light)" in page


def test_the_console_sends_installation_to_the_download_page() -> None:
    config = json.loads((ROOT / "admin-web" / "vercel.json").read_text(encoding="utf-8"))
    assert {
        "source": "/installation",
        "destination": "https://reportwhatslit-apk.vercel.app/",
        "permanent": False,
    } in config["redirects"]
