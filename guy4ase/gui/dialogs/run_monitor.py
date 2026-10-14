"""Generic UI for monitoring one calculation runner."""
from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Thread
from typing import Any

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.execution_cancellation import RunCancellation


logger = logging.getLogger(__name__)


def state_label(state: Any) -> str:
    value = getattr(state, "value", state)
    return str(value).replace("_", " ").capitalize()


class RunMonitorWindow(QDialog):
    """Display one calculation worker without knowing how its runner was created.

    The caller owns launch/attach/persistence semantics. ``worker_factory`` only
    has to return a QObject exposing ``run`` and the usual output/status/error/
    finished/cancelled signals. The worker registers its concrete runner in the
    supplied :class:`RunCancellation`.
    """

    refreshed = pyqtSignal(str)

    def __init__(
        self,
        worker_factory: Callable[[RunCancellation], QObject],
        parent: QWidget | None = None,
        *,
        title: str = "Calculation Run",
        header: str | None = None,
        initial_status: str = "",
        warning_title: str = "Warning",
        on_finished: Callable[[Any], None] | None = None,
        background_thread_factory: Callable[..., Any] = Thread,
        autostart: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.resize(900, 600)

        self._worker_factory = worker_factory
        self._finished_callback = on_finished
        self._warning_title = warning_title
        self._background_thread_factory = background_thread_factory
        self._cancellation = RunCancellation()
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._close_requested = False
        self.refreshed.connect(self._set_status)

        layout = QVBoxLayout(self)
        if header:
            header_widget = QLabel(header, self)
            header_widget.setWordWrap(True)
            layout.addWidget(header_widget)

        self._status = QLabel(initial_status, self)
        layout.addWidget(self._status)

        self._output = QTextEdit(self)
        self._output.setReadOnly(True)
        layout.addWidget(self._output, 1)

        buttons = QHBoxLayout()
        self._stop_btn = QPushButton("Stop", self)
        self._stop_btn.clicked.connect(self._on_stop)
        buttons.addWidget(self._stop_btn)

        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.setToolTip(
            "Refresh the backend run state without blocking the GUI."
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        buttons.addWidget(self._refresh_btn)
        buttons.addStretch(1)

        self._close_btn = QPushButton("Close", self)
        self._close_btn.clicked.connect(self.close)
        buttons.addWidget(self._close_btn)
        layout.addLayout(buttons)

        if autostart:
            self.start()

    @property
    def runner(self) -> Any | None:
        return self._cancellation.runner

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._thread is not None and self._thread.isRunning():
            self._close_requested = True
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def start(self) -> None:
        """Start the worker exactly once after the caller has established ownership."""
        if self._thread is not None:
            raise RuntimeError("run monitor worker has already been started")
        self._start_worker()

    def _start_worker(self) -> None:
        thread = QThread(self)
        worker = self._worker_factory(self._cancellation)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
        if hasattr(worker, "warning"):
            worker.warning.connect(self._on_warning)
        worker.error.connect(self._on_error)
        worker.finished.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)

        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        self._worker = worker
        thread.start()

    @pyqtSlot()
    def _thread_finished(self) -> None:
        if self._close_requested:
            self.close()

    @pyqtSlot(str)
    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    @pyqtSlot(str, str)
    def _append_output(self, text: str, kind: str) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if kind in {"err", "stderr"}:
            fmt.setForeground(QColor("red"))
            fmt.setFontWeight(QFont.Weight.Bold)
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    @pyqtSlot()
    def _on_stop(self) -> None:
        self._stop_btn.setEnabled(False)
        self._cancellation.request()

    @pyqtSlot()
    def _on_refresh(self) -> None:
        runner = self._cancellation.runner
        if runner is None:
            return

        def refresh() -> None:
            try:
                state = runner.state
            except Exception as exc:  # noqa: BLE001 - backend status boundary
                logger.exception("Failed to refresh calculation run state")
                self.refreshed.emit(f"Refresh failed: {exc}")
                return
            self.refreshed.emit(state_label(state))

        self._background_thread_factory(
            target=refresh,
            name="run-refresh",
            daemon=True,
        ).start()

    @pyqtSlot(str)
    def _on_warning(self, message: str) -> None:
        QMessageBox.warning(self, self._warning_title, message)

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        self._append_output(f"\n[ERROR] {message}\n", "stderr")
        self._stop_btn.setEnabled(False)

    @pyqtSlot()
    def _on_cancelled(self) -> None:
        self._stop_btn.setEnabled(False)

    @pyqtSlot(object)
    def _on_finished(self, result: object) -> None:
        try:
            if self._finished_callback is not None:
                self._finished_callback(result)
        finally:
            self._stop_btn.setEnabled(False)
