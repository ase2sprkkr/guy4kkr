"""Responsive modal waiting for short-lived workspace operations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from guy4ase.gui.application.workspace_controller import (
    Busy,
    Completed,
    DocumentChange,
)

_T = TypeVar("_T")
_MISSING = object()


@dataclass(frozen=True)
class WorkspaceWaitResult(Generic[_T]):
    """Whether a pending GUI operation ran, plus its optional return value."""

    completed: bool
    value: _T | None = None


def wait_for_workspace(
    parent: QWidget,
    operation: Callable[[], Completed[_T] | Busy],
) -> WorkspaceWaitResult[_T]:
    """Run an operation, keeping Qt responsive while its workspace is busy.

    Two immediate attempts avoid showing a dialog for a lock released between
    adjacent event-loop turns. If both fail, an indeterminate modal dialog
    retries via ``QTimer``. Canceling abandons this operation only; it never
    interrupts the lock owner or its worker thread.
    """
    busy: Busy | None = None
    for _attempt in range(2):
        attempt = operation()
        if isinstance(attempt, Completed):
            return WorkspaceWaitResult(True, attempt.value)
        busy = attempt

    assert busy is not None
    dialog = QProgressDialog(parent)
    dialog.setWindowTitle("Please Wait")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setRange(0, 0)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setCancelButtonText("Cancel")

    def update_label(state: Busy) -> None:
        dialog.setLabelText(
            "The workspace is currently busy.\n"
            f"Current operation: {state.active_reason}.\n"
            f"Waiting operation: {state.requested_reason}."
        )

    update_label(busy)
    result: Any = _MISSING
    error: Exception | None = None

    def retry() -> None:
        nonlocal result, error
        try:
            attempt = operation()
        except Exception as exc:  # noqa: BLE001 - re-raised outside Qt callback
            error = exc
            dialog.reject()
        else:
            if isinstance(attempt, Busy):
                update_label(attempt)
            else:
                result = attempt.value
                dialog.accept()

    timer = QTimer(dialog)
    timer.setInterval(25)
    timer.timeout.connect(retry)
    dialog.canceled.connect(dialog.reject)
    timer.start()
    dialog.exec()
    timer.stop()

    if error is not None:
        raise error
    if result is not _MISSING:
        return WorkspaceWaitResult(True, result)
    return WorkspaceWaitResult(False)


def wait_for_workspace_action(
    parent: QWidget,
    operation: Callable[[], Completed[_T] | Busy],
) -> bool:
    """Boolean convenience API for button handlers without a return value."""
    return wait_for_workspace(parent, operation).completed


def wait_for_document_change(
    parent: QWidget,
    operation: Callable[[], Completed[DocumentChange] | Busy],
) -> bool:
    """Wait for a generation-sensitive change and explain stale rejection."""
    outcome = wait_for_workspace(parent, operation)
    if not outcome.completed:
        return False
    if outcome.value is DocumentChange.STALE:
        QMessageBox.information(
            parent,
            "Document Changed",
            "The document changed while the editor was open. "
            "Its older draft was not applied.",
        )
        return False
    return True
