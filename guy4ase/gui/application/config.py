"""Per-user configuration paths shared by GUI persistence services."""
from __future__ import annotations

from pathlib import Path

import platformdirs


def config_home() -> Path:
    """Return Guy4ASE's per-user configuration directory."""
    return Path(platformdirs.user_config_dir("guy4ase", appauthor="ase2sprkkr"))
