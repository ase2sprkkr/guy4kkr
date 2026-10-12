"""Run short blocking operations without freezing the Qt event loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QProgressDialog, QWidget

_T = TypeVar("_T")
_MISSING = object()


class _ModalTaskWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self._operation = operation

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as exc:  # noqa: BLE001 - re-raised in the GUI thread
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)


def run_modal_task(
    parent: QWidget | None,
    operation: Callable[[], _T],
    *,
    title: str = "Please Wait",
    label: str = "Working…",
) -> _T:
    """Run ``operation`` in a worker while showing a responsive modal wait.

    Non-GUI callers may pass ``None``; in that case the operation runs directly.
    """
    if parent is None or not isinstance(parent, QWidget):
        return operation()

    dialog = QProgressDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setRange(0, 0)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setCancelButton(None)

    result: Any = _MISSING
    error: Exception | None = None

    thread = QThread()
    worker = _ModalTaskWorker(operation)
    worker.moveToThread(thread)

    def succeeded(value: Any) -> None:
        nonlocal result
        result = value
        dialog.accept()

    def failed(exc: Exception) -> None:
        nonlocal error
        error = exc
        dialog.reject()

    worker.succeeded.connect(succeeded)
    worker.failed.connect(failed)
    worker.succeeded.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.succeeded.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.started.connect(worker.run)

    thread.start()
    dialog.exec()
    thread.quit()
    thread.wait()

    if error is not None:
        raise error
    if result is _MISSING:
        raise RuntimeError("Modal task ended without a result.")
    return result
