from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from threading import Lock
from typing import Any

from ase2sprkkr.sprkkr.calculator import SPRKKR
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from guy4ase.gui.application.result_loading import load_result
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.widgets.input_parameters.dataset import (
    dataset_value,
    filename_component,
)


logger = logging.getLogger(__name__)


class _RunCancellation:
    """Bridge a GUI stop request to a process that may not exist yet."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requested = False
        self._process: Any | None = None

    @property
    def requested(self) -> bool:
        with self._lock:
            return self._requested

    def register(self, process: Any) -> bool:
        """Register the process and return whether it may be started."""
        with self._lock:
            if self._requested:
                return False
            self._process = process
            return True

    def request(self) -> None:
        with self._lock:
            if self._requested:
                return
            self._requested = True
            process = self._process

        if process is not None:
            process.stop_the_process()


class _SprkkrRunWorker(QObject):
    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # LoadedResult
    cancelled = pyqtSignal()
    activityStarted = pyqtSignal(object)
    activityEnded = pyqtSignal(object)

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: _RunCancellation | None = None,
    ):
        super().__init__()
        self._request = request
        self._cancellation = cancellation or _RunCancellation()
        self.run_id = object()

    def _emit_cancelled(self) -> None:
        self.status.emit("Cancelled")
        self.cancelled.emit()

    def _file_names(self) -> tuple[str, str, str]:
        """Use DATASET as the visible namespace for files owned by this run."""
        dataset = dataset_value(self._request.input_parameters)
        if dataset is None:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        base = filename_component(dataset)
        if not base:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        return f"{base}_%T.inp", f"{base}.pot", f"{base}_%T.out"

    @pyqtSlot()
    def run(self) -> None:
        self.activityStarted.emit(self.run_id)
        running = False
        try:
            def read_callback(text: str, kind: str) -> None:
                # Called from the runner while it produces output.
                self.output.emit(text, kind)

            self.status.emit("Preparing calculation…")
            calc = SPRKKR()
            input_file, potential_file, output_file = self._file_names()
            process = calc.calculate(
                atoms=self._request.atoms,
                input_parameters=self._request.input_parameters,
                directory=self._request.directory,
                input_file=input_file,
                potential_file=potential_file,
                output_file=output_file,
                empty_spheres=False,
                run_async=True,
                read_callback=read_callback,
                print_output=False,
            )

            if not self._cancellation.register(process):
                self._emit_cancelled()
                return

            running = True
            self.status.emit("Running…")
            result = process.run()
            if self._cancellation.requested:
                self._emit_cancelled()
                return

            self.status.emit("Loading result…")
            loaded = load_result(
                result,
                fallback_directory=self._request.directory,
            )
            self.status.emit("Finished")
            self.finished.emit(loaded)
        except asyncio.CancelledError:
            self._emit_cancelled()
        except Exception as exc:  # noqa: BLE001 - worker exception boundary
            if running and self._cancellation.requested:
                self._emit_cancelled()
            else:
                logger.exception("SPR-KKR calculation or result loading failed")
                self.error.emit(str(exc))
        finally:
            self.activityEnded.emit(self.run_id)


class SprkkrRunWindow(QDialog):
    def __init__(
        self,
        atoms: Any = None,
        input_parameters: Any = None,
        directory: str | None = None,
        parent: Any | None = None,
        *,
        request: CalculationRequest | None = None,
        on_finished: Callable[[Any], None] | None = None,
        on_activity_started: Callable[[Any], None] | None = None,
        on_activity_ended: Callable[[Any], None] | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("SPRKKR Run")
        self.resize(900, 600)

        self._thread: QThread | None = None
        self._worker: _SprkkrRunWorker | None = None
        self._finished_callback = on_finished
        self._activity_started_callback = on_activity_started
        self._activity_ended_callback = on_activity_ended
        self._close_requested = False

        layout = QVBoxLayout(self)

        if request is None:
            if directory is None:
                raise ValueError("A calculation directory is required.")
            request = CalculationRequest(
                atoms=atoms,
                input_parameters=input_parameters,
                directory=directory,
                generation=0,
            )

        header = QLabel(f"Directory: {request.directory}")
        header.setWordWrap(True)
        layout.addWidget(header)

        self._status = QLabel("")
        layout.addWidget(self._status)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        layout.addWidget(self._output, 1)

        btn_row = QHBoxLayout()
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch(1)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        self._start(request)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._thread is not None and self._thread.isRunning():
            self._close_requested = True
            self._on_stop()
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def _start(
        self,
        request: CalculationRequest,
    ) -> None:
        thread = QThread(self)
        self._cancellation = _RunCancellation()
        worker = _SprkkrRunWorker(request, self._cancellation)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)
        if self._activity_started_callback is not None:
            worker.activityStarted.connect(self._activity_started_callback)
        if self._activity_ended_callback is not None:
            worker.activityEnded.connect(self._activity_ended_callback)

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

        is_err = kind in {"err", "stderr"}

        fmt = QTextCharFormat()
        if is_err:
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

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        self._append_output(f"\n[ERROR] {message}\n", "stderr")
        self._stop_btn.setEnabled(False)

    @pyqtSlot()
    def _on_cancelled(self) -> None:
        self._stop_btn.setEnabled(False)

    @pyqtSlot(object)
    def _on_finished(self, _result: object) -> None:
        try:
            if self._finished_callback is not None:
                self._finished_callback(_result)
        finally:
            self._stop_btn.setEnabled(False)
