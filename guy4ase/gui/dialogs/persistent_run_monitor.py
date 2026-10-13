"""Monitor an already submitted persistent ASE2SPRKKR calculation."""
from __future__ import annotations

import asyncio
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
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.dialogs.run_calculation import _RunCancellation


logger = logging.getLogger(__name__)


def _state_label(state: Any) -> str:
    value = getattr(state, "value", state)
    return str(value).replace("_", " ").capitalize()


class _PersistentRunWorker(QObject):
    output = pyqtSignal(str, str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(
        self,
        source: PersistentJobSource,
        job_id: str,
        cancellation: _RunCancellation | None = None,
    ) -> None:
        super().__init__()
        self._source = source
        self._job_id = job_id
        self._cancellation = cancellation or _RunCancellation()

    def _emit_cancelled(self) -> None:
        self.status.emit("Cancelled")
        self.cancelled.emit()

    @pyqtSlot()
    def run(self) -> None:
        attached = False
        try:
            self.status.emit("Attaching to calculation…")

            def output_listener(text: str, kind: str) -> None:
                self.output.emit(text, kind)

            # ASE2SPRKKR installs output_listener before starting the attach
            # monitor, so replayed output cannot race with this GUI hookup.
            runner = self._source.attach(
                self._job_id,
                output_listener=output_listener,
            )
            if not self._cancellation.register(runner):
                runner.cancel()
                self._emit_cancelled()
                return

            attached = True
            self.status.emit(_state_label(runner.state))
            result = runner.wait()
            if self._cancellation.requested:
                self._emit_cancelled()
                return

            self.status.emit("Finished")
            self.finished.emit(result)
        except asyncio.CancelledError:
            self._emit_cancelled()
        except Exception as exc:  # noqa: BLE001 - persisted/backend boundary
            if attached and self._cancellation.requested:
                self._emit_cancelled()
            else:
                logger.exception("Failed to monitor persistent SPR-KKR calculation")
                self.error.emit(str(exc))


class PersistentRunMonitorWindow(QDialog):
    """Live output window for a persistent job selected from history."""

    refreshed = pyqtSignal(str)

    def __init__(
        self,
        job: PersistentJob,
        source: PersistentJobSource,
        parent: QWidget | None = None,
        *,
        on_finished: Callable[[Any], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Monitor {job.task or 'SPRKKR'} Calculation")
        self.resize(900, 600)

        self._job = job
        self._source = source
        self._finished_callback = on_finished
        self._thread: QThread | None = None
        self._worker: _PersistentRunWorker | None = None
        self._close_requested = False
        self.refreshed.connect(self._set_status)

        layout = QVBoxLayout(self)
        title = job.dataset or job.id
        header = QLabel(
            f"{title}\n{job.target} · {job.directory}",
            self,
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._status = QLabel(_state_label(job.state), self)
        layout.addWidget(self._status)

        self._output = QTextEdit(self)
        self._output.setReadOnly(True)
        layout.addWidget(self._output, 1)

        buttons = QHBoxLayout()
        self._stop_btn = QPushButton("Stop", self)
        self._stop_btn.clicked.connect(self._on_stop)
        buttons.addWidget(self._stop_btn)

        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.clicked.connect(self._on_refresh)
        buttons.addWidget(self._refresh_btn)
        buttons.addStretch(1)

        self._close_btn = QPushButton("Close", self)
        self._close_btn.clicked.connect(self.close)
        buttons.addWidget(self._close_btn)
        layout.addLayout(buttons)

        self._start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._thread is not None and self._thread.isRunning():
            # Detach only. The backend calculation is persistent and Stop is
            # deliberately the only UI action that cancels it.
            self._close_requested = True
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def _start(self) -> None:
        thread = QThread(self)
        self._cancellation = _RunCancellation()
        worker = _PersistentRunWorker(
            self._source,
            self._job.id,
            self._cancellation,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
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
            self._set_status("Attaching to calculation…")
            return

        def refresh() -> None:
            try:
                state = runner.state
            except Exception as exc:  # noqa: BLE001 - backend status boundary
                logger.exception("Failed to refresh persistent SPR-KKR run state")
                self.refreshed.emit(f"Refresh failed: {exc}")
                return
            self.refreshed.emit(_state_label(state))

        Thread(target=refresh, name="sprkkr-persistent-refresh", daemon=True).start()

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
