"""Normalized facts used by Guided workflow presentation policy."""
from __future__ import annotations

from enum import Enum, auto


class EmptySpheresAction(Enum):
    """Recommended empty-sphere action for the current workspace draft."""

    ADD = auto()
    RECALCULATE = auto()


class ScfProgress(Enum):
    """Semantic progress of the active SCF potential.

    These values deliberately hide SPR-KKR's raw ``SCFSTATUS`` strings from
    presentation code while retaining enough detail for useful Guided messages.
    """

    NOT_STARTED = auto()
    ITERATING = auto()
    BULK = auto()
    LEFT_BULK = auto()
    RIGHT_BULK = auto()
    INTERACTION_ZONE = auto()
    CONVERGED = auto()
    UNKNOWN = auto()

    @property
    def can_continue(self) -> bool:
        """Return whether the current state represents an interrupted SCF run."""
        return self in {
            ScfProgress.ITERATING,
            ScfProgress.BULK,
            ScfProgress.LEFT_BULK,
            ScfProgress.RIGHT_BULK,
            ScfProgress.INTERACTION_ZONE,
        }


_SCF_PROGRESS_BY_STATUS = {
    "ITR": ScfProgress.ITERATING,
    "ITR-BULK": ScfProgress.BULK,
    "ITR-L-BULK": ScfProgress.LEFT_BULK,
    "ITR-R-BULK": ScfProgress.RIGHT_BULK,
    "ITR-I-ZONE": ScfProgress.INTERACTION_ZONE,
}


def classify_scf_progress(
    status: str | None,
    *,
    converged: bool,
) -> ScfProgress:
    """Normalize backend SCF state for application and presentation policy."""
    if converged:
        return ScfProgress.CONVERGED
    if status is None:
        return ScfProgress.NOT_STARTED

    normalized = str(status).strip().upper()
    if not normalized or normalized == "START":
        return ScfProgress.NOT_STARTED
    return _SCF_PROGRESS_BY_STATUS.get(normalized, ScfProgress.UNKNOWN)
