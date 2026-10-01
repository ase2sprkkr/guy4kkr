"""The mutable document shared by the application's windows.

The workspace deliberately has no Qt dependency.  Windows render it and offer
operations on it, but neither owns a second copy of the calculation state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkspaceState:
    """Passive data held by the application's semantic workspace controller.

    Application code reads these facets directly but publishes changes only
    through ``WorkspaceController`` document transitions.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None
