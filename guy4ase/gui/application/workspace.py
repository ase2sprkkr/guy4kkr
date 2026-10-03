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

    Values exposed here are borrowed references, not owned copies or read-only
    proxies. Application code may render them directly, but confirmed changes
    must be published through ``WorkspaceController`` document transitions.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None
