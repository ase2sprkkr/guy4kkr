"""Compatibility shim for the former GUI run registry.

Run ownership, persistence and collision policy belong to ASE2SPRKKR execution.
Guy4ASE no longer keeps a second registry of live calculations. The class is
kept temporarily only so older view/test construction signatures can be
removed independently.
"""
from __future__ import annotations

from threading import Lock


class ActiveRunRegistry:
    """Deprecated no-op compatibility object; not an execution registry."""

    def __init__(self) -> None:
        self.launch_lock = Lock()

    @property
    def active(self) -> tuple[object, ...]:
        return ()
