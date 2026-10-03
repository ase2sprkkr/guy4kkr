"""Application-scoped registry of running calculation workers."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class ActiveRunRegistry(QObject):
    """Track worker lifetimes independently of the workspace document."""

    countChanged = pyqtSignal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runs: set[Any] = set()

    @property
    def count(self) -> int:
        return len(self._runs)

    @pyqtSlot(object)
    def register(self, run_id: Any) -> None:
        before = len(self._runs)
        self._runs.add(run_id)
        if len(self._runs) != before:
            self.countChanged.emit(len(self._runs))

    @pyqtSlot(object)
    def unregister(self, run_id: Any) -> None:
        before = len(self._runs)
        self._runs.discard(run_id)
        if len(self._runs) != before:
            self.countChanged.emit(len(self._runs))
