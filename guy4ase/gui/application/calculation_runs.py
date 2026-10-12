"""Application-scoped coordination for calculation launches."""
from __future__ import annotations

from threading import Lock

from ase2sprkkr.execution import RunRegistry


class ActiveRunRegistry(RunRegistry):
    """Backend run registry with a short GUI launch critical section.

    Run state and collision ownership live in :class:`RunRegistry`. The
    additional lock only serializes preflight -> preparation -> submit so two
    GUI workers cannot both prepare the same files before either run is
    registered.
    """

    def __init__(self) -> None:
        super().__init__()
        self.launch_lock = Lock()
