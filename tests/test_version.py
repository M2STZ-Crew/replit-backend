"""The version is declared in four places; this keeps them from drifting.

MINOR tracks the Master Context generation: 1.11.x implements Master Context
v11. That makes "which build implements which spec" answerable without reading
a changelog, which matters when the document is the thing being defended.

Nothing enforces agreement between a pyproject version, a Pydantic default and
two package.json files — they are four unrelated files that happen to mean the
same thing, and the surest way for them to drift is for one release to update
three of them. /health reports the backend's, so a stale default there is a
number an operator will quote back at you.

The mobile app's pubspec.yaml lives in the other repository, so it cannot be
checked here; it is versioned by hand alongside these.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.core.config import Settings

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _package_version(app: str) -> str:
    data = json.loads((_ROOT / app / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _settings_default() -> str:
    """The declared default, not the running value.

    Read from the field rather than from get_settings() because APP_VERSION can
    be overridden in the environment, and what ships is the default.
    """
    return str(Settings.model_fields["app_version"].default)


def test_every_surface_declares_the_same_version() -> None:
    declared = {
        "pyproject.toml": _pyproject_version(),
        "app/core/config.py": _settings_default(),
        "admin-web/package.json": _package_version("admin-web"),
        "observer-web/package.json": _package_version("observer-web"),
    }
    assert len(set(declared.values())) == 1, f"versions disagree: {declared}"


def test_the_version_is_a_three_part_semantic_version() -> None:
    parts = _pyproject_version().split(".")
    assert len(parts) == 3, "expected MAJOR.MINOR.PATCH"
    assert all(p.isdigit() for p in parts), "every part is a number"


def test_the_minor_tracks_the_master_context_generation() -> None:
    """1.11.x implements Master Context v11, so the file must be the v11 one."""
    minor = int(_pyproject_version().split(".")[1])
    assert (_ROOT / f"MASTER_CONTEXT_v{minor}.md").exists(), (
        f"version claims Master Context v{minor}, but no MASTER_CONTEXT_v{minor}.md "
        "is in the repository"
    )
