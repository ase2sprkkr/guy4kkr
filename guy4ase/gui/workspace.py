"""The mutable document shared by the application's windows.

The workspace deliberately has no Qt dependency.  Windows render it and offer
operations on it, but neither owns a second copy of the calculation state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkspaceState:
    """Structure, calculation setup and result currently being worked on."""

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None

    def reset(self) -> None:
        """Discard the current document without affecting persisted history."""
        self.atoms = None
        self.input_parameters = None
        self.directory = None
        self.potential_path = None
        self.result = None
