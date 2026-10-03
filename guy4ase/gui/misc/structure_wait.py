"""Responsive modal waiting for short-lived structure operations."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from guy4ase.gui.application.workspace_controller import Busy, DocumentChange

_T = TypeVar("_T")
_MISSING = object()


def wait_for_structure(
    parent: QWidget,
    operation: Callable[[], _T | Busy],
) -> _T | Busy:
    """Run a structure operation without ever blocking the Qt event loop.

    Canceling abandons only this waiting GUI action. It never interrupts the
    worker that currently owns the structure gate. A canceled wait returns the
    last ``Busy`` value, so operations returning ``None`` need no wrapper.
    """
    busy: Busy | None = None
    for _attempt in range(2):
        attempt = operation()
        if not isinstance(attempt, Busy):
            return attempt
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
            "The structure is currently busy.\n"
            f"Current operation: {state.active_reason}.\n"
            f"Waiting operation: {state.requested_reason}."
        )

    update_label(busy)
    result: Any = _MISSING
    error: Exception | None = None

    def retry() -> None:
        nonlocal busy, result, error
        try:
            attempt = operation()
        except Exception as exc:  # noqa: BLE001 - re-raised outside Qt callback
            error = exc
            dialog.reject()
        else:
            if isinstance(attempt, Busy):
                busy = attempt
                update_label(attempt)
            else:
                result = attempt
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
        return result
    return busy


def document_change_applied(parent: QWidget, change: DocumentChange) -> bool:
    """Explain a rejected stale draft at the GUI workflow boundary."""
    if change is DocumentChange.APPLIED:
        return True
    QMessageBox.information(
        parent,
        "Document Changed",
        "The document changed while the editor was open. "
        "Its older draft was not applied.",
    )
    return False
