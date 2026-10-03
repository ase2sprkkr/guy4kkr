"""Qt-owned silent retries for nonblocking structure refreshes."""
from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial
from typing import Generic, TypeVar

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from guy4ase.gui.application.workspace_controller import (
    Busy,
    StructureAccessGate,
)

_T = TypeVar("_T")


class _StructureRetryJob(QObject, Generic[_T]):
    """Own one refresh retry until it completes or its adapter is destroyed."""

    def __init__(
        self,
        parent: QObject,
        operation: Callable[[], _T | Busy],
        on_completed: Callable[[_T], None] | None,
        on_error: Callable[[Exception], None] | None,
        interval_ms: int,
    ) -> None:
        super().__init__(parent)
        self._operation: Callable[[], _T | Busy] | None = operation
        self._on_completed = on_completed
        self._on_error = on_error
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._retry)

    def start(self) -> None:
        try:
            self._attempt()
        except Exception:
            self.deleteLater()
            raise

    @pyqtSlot()
    def _retry(self) -> None:
        try:
            self._attempt()
        except Exception as exc:  # noqa: BLE001 - Qt cannot propagate slot errors
            self.deleteLater()
            if self._on_error is not None:
                self._on_error(exc)
            else:
                sys.excepthook(type(exc), exc, exc.__traceback__)

    def _attempt(self) -> None:
        operation = self._operation
        if operation is None:
            return
        attempt = operation()
        if isinstance(attempt, Busy):
            self._timer.start()
            return

        on_completed = self._on_completed
        self._operation = None
        self._on_completed = None
        try:
            if on_completed is not None:
                on_completed(attempt)
        finally:
            self.deleteLater()


class QtStructureAccess(QObject):
    """Retry nonessential structure reads without showing a modal dialog."""

    def __init__(
        self,
        gate: StructureAccessGate,
        parent: QObject,
        *,
        retry_interval_ms: int = 25,
    ) -> None:
        super().__init__(parent)
        self._gate = gate
        self._retry_interval_ms = retry_interval_ms

    def retry(
        self,
        callback: Callable[[], _T],
        *,
        reason: str,
        on_completed: Callable[[_T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> QObject:
        """Try a short structure read now and silently retry while busy."""
        operation = partial(self._gate.try_call, reason, callback)
        job = _StructureRetryJob(
            self,
            operation,
            on_completed,
            on_error,
            self._retry_interval_ms,
        )
        job.start()
        return job
