"""Small Qt-independent presentation vocabulary shared by GUI views."""
from __future__ import annotations

from typing import Literal

from guy4ase.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction

ActionCategory = Literal[
    "structure", "load", "calculation", "destructive", "neutral"
]


def empty_spheres_action_title(action: _EmptySpheresAction) -> str:
    """Return the shared user-facing label for an empty-sphere recommendation."""
    return {
        _EmptySpheresAction.ADD: "Add Empty Spheres",
        _EmptySpheresAction.RECALCULATE: "Recalculate Empty Spheres",
    }[action]
