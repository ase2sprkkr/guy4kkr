"""Qt-free leaf value types shared across GUI architecture layers.

This module contains semantic vocabulary only: immutable value types with no
state ownership, workflow policy, presentation copy, or dependencies on other
``guy4ase.gui`` modules.
"""
from enum import Enum, auto


class EmptySpheresAction(Enum):
    """Recommended empty-sphere action for the current workspace draft."""

    ADD = auto()
    RECALCULATE = auto()
