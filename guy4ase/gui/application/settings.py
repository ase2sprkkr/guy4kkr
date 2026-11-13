"""Persistent application-wide user preferences."""
from __future__ import annotations

import json
from pathlib import Path

from guy4ase.gui.application.config import config_home


def default_settings_path() -> Path:
    """Return the per-user application settings path."""
    return config_home() / "settings.json"


class ApplicationSettings:
    """Load and persist application-wide user preferences."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self.viewer = "ase"

    def load(self) -> None:
        """Load settings; corrupt or unreadable files keep defaults."""
        self.viewer = "ase"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (
            FileNotFoundError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return
        if not isinstance(data, dict):
            return
        viewer = data.get("viewer")
        if isinstance(viewer, str) and viewer.strip():
            self.viewer = viewer.strip()

    def save(self) -> bool:
        """Persist settings, returning false when the file is not writable."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"viewer": self.viewer}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return False
        return True
