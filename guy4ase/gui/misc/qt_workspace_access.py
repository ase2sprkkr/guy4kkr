"""Qt scheduling adapter for nonblocking workspace access."""
from __future__ import annotations

import sys
from collections.abc import Callable
from functools import partial
from typing import Any, Generic, TypeVar

from PyQt6.QtCore import QObject, QTimer, pyqtSlot
from PyQt6.QtWidgets import QWidget

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    Busy,
    Completed,
    DocumentChange,
    WorkspaceController,
)
from guy4ase.gui.misc.workspace_wait import (
    WorkspaceWaitResult,
    wait_for_document_change,
    wait_for_workspace,
    wait_for_workspace_action,
)

_T = TypeVar("_T")


class _WorkspaceRetryJob(QObject, Generic[_T]):
    """Own one retrying operation until it completes or its adapter dies."""

    def __init__(
        self,
        parent: QObject,
        operation: Callable[[], Completed[_T] | Busy],
        on_completed: Callable[[_T], None] | None,
        on_error: Callable[[Exception], None] | None,
        interval_ms: int,
    ) -> None:
        super().__init__(parent)
        self._operation: Callable[[], Completed[_T] | Busy] | None = operation
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
                on_completed(attempt.value)
        finally:
            self.deleteLater()


class QtWorkspaceAccess(QObject):
    """Apply Qt retry and lifetime semantics to one workspace access gate."""

    def __init__(
        self,
        controller: WorkspaceController,
        parent: QWidget,
        *,
        retry_interval_ms: int = 25,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._dialog_parent = parent
        self._retry_interval_ms = retry_interval_ms

    def retry(
        self,
        callback: Callable[[], _T],
        *,
        reason: str,
        on_completed: Callable[[_T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> QObject:
        """Retry a callback that must run while holding this adapter's gate."""
        return self.retry_call(
            partial(self._controller.access_gate.try_call, reason, callback),
            on_completed=on_completed,
            on_error=on_error,
        )

    def retry_call(
        self,
        operation: Callable[[], Completed[_T] | Busy],
        *,
        on_completed: Callable[[_T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> QObject:
        """Retry an operation which already returns ``Completed | Busy``."""
        job = _WorkspaceRetryJob(
            self,
            operation,
            on_completed,
            on_error,
            self._retry_interval_ms,
        )
        job.start()
        return job

    def wait(
        self,
        callback: Callable[[], _T],
        *,
        reason: str,
    ) -> WorkspaceWaitResult[_T]:
        """Run a gate callback, showing the cancelable wait dialog if busy."""
        return self.wait_call(
            partial(self._controller.access_gate.try_call, reason, callback)
        )

    def wait_call(
        self,
        operation: Callable[[], Completed[_T] | Busy],
    ) -> WorkspaceWaitResult[_T]:
        """Run a semantic controller operation with modal busy handling."""
        return wait_for_workspace(self._dialog_parent, operation)

    def action(
        self,
        operation: Callable[[], Completed[_T] | Busy],
    ) -> bool:
        """Boolean variant for operations whose value is not needed."""
        return wait_for_workspace_action(self._dialog_parent, operation)

    def change(
        self,
        operation: Callable[[], Completed[DocumentChange] | Busy],
    ) -> bool:
        """Run a generation-sensitive document change."""
        return wait_for_document_change(self._dialog_parent, operation)

    def read_structure(
        self,
        reader: Callable[[Any], _T],
        *,
        reason: str,
    ) -> WorkspaceWaitResult[tuple[int, _T]]:
        """Read a consistent structure snapshot with modal busy handling."""
        return self.wait_call(
            partial(self._controller.read_structure, reader, reason=reason)
        )

    def read_workspace(
        self,
        reader: Callable[[WorkspaceState], _T],
        *,
        reason: str,
    ) -> WorkspaceWaitResult[tuple[int, _T]]:
        """Read a consistent workspace snapshot with modal busy handling."""
        return self.wait_call(
            partial(self._controller.read_workspace, reader, reason=reason)
        )
