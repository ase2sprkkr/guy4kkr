from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Callable
from threading import Lock, Thread
from typing import Any

from ase2sprkkr.execution import MpiNotFoundWarning
from ase2sprkkr.sprkkr.calculator import SPRKKR
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
)

from guy4ase.gui.application.result_loading import load_result
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.widgets.input_parameters.dataset import (
    dataset_value,
    filename_component,
)


logger = logging.getLogger(__name__)


class _RunCancellation:
    """Bridge a GUI stop request to a runner that may not exist yet."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requested = False
        self._runner: Any | None = None

    @property
    def requested(self) -> bool:
        with self._lock:
            return self._requested

    @property
    def runner(self) -> Any | None:
        """Return the current runner for non-blocking status refresh."""
        with self._lock:
            return self._runner

    def register(self, runner: Any) -> bool:
        """Register the runner and return whether it may be started."""
        with self._lock:
            if self._requested:
                return False
            self._runner = runner
            return True

    @staticmethod
    def _cancel_runner(runner: Any) -> None:
        try:
            runner.cancel()
        except Exception:  # noqa: BLE001 - backend cancellation boundary
            logger.exception("Failed to cancel SPR-KKR calculation")

    def request(self) -> None:
        with self._lock:
            if self._requested:
                return
            self._requested = True
            runner = self._runner

        if runner is not None:
            Thread(
                target=self._cancel_runner,
                args=(runner,),
                name="sprkkr-cancel",
                daemon=True,
            ).start()


class _SprkkrRunWorker(QObject):
    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # LoadedResult
    cancelled = pyqtSignal()

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: _RunCancellation | None = None,
        *,
        profile_name: str | None = None,
    ):
        super().__init__()
        self._request = request
        self._profile_name = profile_name
        self._cancellation = cancellation or _RunCancellation()

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

    def _with_mpi_warnings(self, operation):
        """Run one backend operation and surface only the dedicated MPI warning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", MpiNotFoundWarning)
            result = operation()

        for item in caught:
            if issubclass(item.category, MpiNotFoundWarning):
                self.warning.emit(str(item.message))
            else:
                warnings.showwarning(
                    item.message,
                    item.category,
                    item.filename,
                    item.lineno,
                    file=item.file,
                    line=item.line,
                )
        return result

    def _create_runner(self, calculator: SPRKKR, **kwargs):
        return self._with_mpi_warnings(lambda: calculator.create_run(**kwargs))

    def _launch(self, calculator: SPRKKR):
        input_file, potential_file, output_file = self._file_names()

        def read_callback(text: str, kind: str) -> None:
            self.output.emit(text, kind)

        runner = self._create_runner(
            calculator,
            atoms=self._request.atoms,
            input_parameters=self._request.input_parameters,
            directory=self._request.directory,
            input_file=input_file,
            potential_file=potential_file,
            output_file=output_file,
            empty_spheres=False,
            read_callback=read_callback,
            print_output=False,
        )
        if not self._cancellation.register(runner):
            runner.cancel()
            return None
        self._with_mpi_warnings(runner.submit)
        return runner

    @pyqtSlot()
    def run(self) -> None:
        running = False
        try:
            self.status.emit("Preparing calculation…")
            calculator = (
                SPRKKR()
                if self._profile_name is None
                else SPRKKR(profile=self._profile_name)
            )
            runner = self._launch(calculator)
            if runner is None:
                self._emit_cancelled()
                return

            running = True
            reference = runner.reference
            if reference is not None:
                target = reference.computer or reference.executor
                self.status.emit(f"Running on {target}…")
            else:
                self.status.emit("Running…")
            result = runner.wait()
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
        except Exception as exc:  # noqa: BLE001 - worker/backend boundary
            if running and self._cancellation.requested:
                self._emit_cancelled()
            else:
                logger.exception("SPR-KKR calculation or result loading failed")
                self.error.emit(str(exc))


class SprkkrRunWindow(QDialog):
    refreshed = pyqtSignal(str)

    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        on_finished: Callable[[Any], None] | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("SPRKKR Run")
        self.resize(900, 600)

        self._thread: QThread | None = None
        self._worker: _SprkkrRunWorker | None = None
        self._finished_callback = on_finished
        self._close_requested = False
        self._profile_name = profile_name
        self.refreshed.connect(self._set_status)

        layout = QVBoxLayout(self)

        header = QLabel(f"Directory: {request.directory}")
        header.setWordWrap(True)
        layout.addWidget(header)
        if profile_description:
            profile = QLabel(profile_description)
            profile.setWordWrap(True)
            layout.addWidget(profile)

        self._status = QLabel("")
        layout.addWidget(self._status)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        layout.addWidget(self._output, 1)

        btn_row = QHBoxLayout()
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self._stop_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip(
            "Refresh the backend run state without blocking the GUI. "
            "Output continues to use the runner's normal live listener."
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self._refresh_btn)

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

    def _start(self, request: CalculationRequest) -> None:
        thread = QThread(self)
        self._cancellation = _RunCancellation()
        worker = _SprkkrRunWorker(
            request,
            self._cancellation,
            profile_name=self._profile_name,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
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

    @pyqtSlot()
    def _on_refresh(self) -> None:
        runner = self._cancellation.runner
        if runner is None:
            self._set_status("Preparing calculation…")
            return

        def refresh() -> None:
            try:
                state = runner.state
            except Exception as exc:  # noqa: BLE001 - backend status boundary
                logger.exception("Failed to refresh SPR-KKR run state")
                self.refreshed.emit(f"Refresh failed: {exc}")
                return
            value = getattr(state, "value", state)
            self.refreshed.emit(str(value).replace("_", " ").capitalize())

        Thread(target=refresh, name="sprkkr-refresh", daemon=True).start()

    @pyqtSlot(str)
    def _on_warning(self, message: str) -> None:
        QMessageBox.warning(self, "MPI Not Detected", message)

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
