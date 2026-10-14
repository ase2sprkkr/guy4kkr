"""Qt-independent semantic actions derived from the active workspace."""
from enum import Enum, auto


class EmptySpheresAction(Enum):
    """Recommended empty-sphere action for the current workspace draft."""

    ADD = auto()
    RECALCULATE = auto()
