from __future__ import annotations

from collections.abc import Callable
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

from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    StructureAccessGate,
)


class _SprkkrRunWorker(QObject):
    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # result
    preparationFinished = pyqtSignal(object)  # borrowed atoms, lock is released
    activityStarted = pyqtSignal(object)
    activityEnded = pyqtSignal(object)

    def __init__(
        self, request: CalculationRequest, structure_gate: StructureAccessGate
    ):
        super().__init__()
        self._request = request
        self._structure_gate = structure_gate
        self.run_id = object()
        self._process: Any | None = None
        self._stop_requested = False

    @pyqtSlot()
    def run(self) -> None:
        self.activityStarted.emit(self.run_id)
        try:
            def read_callback(text: str, kind: str) -> None:
                # Called from the runner while it produces output.
                self.output.emit(text, kind)

            self.status.emit("Waiting to prepare shared structure…")
            # calculate(run_async=True) performs all shared-Atoms work and
            # writes the input/potential files. KkrProcess.run() below only
            # starts the prepared subprocess and parses its files.
            try:
                def prepare() -> Any:
                    self.status.emit("Preparing calculation…")
                    calc = SPRKKR()
                    return calc.calculate(
                        atoms=self._request.atoms,
                        input_parameters=self._request.input_parameters,
                        directory=self._request.directory,
                        run_async=True,
                        read_callback=read_callback,
                        print_output=False,
                    )

                self._process = self._structure_gate.call(
                    "preparing a calculation", prepare
                )
            finally:
                # A failed preparation may still have lazily materialized the
                # shared structure. The lock is already released here.
                self.preparationFinished.emit(self._request.atoms)

            if self._stop_requested:
                raise RuntimeError("Stopped")

            self.status.emit("Running…")
            result = self._process.run()
            self.status.emit("Finished")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.activityEnded.emit(self.run_id)

    @pyqtSlot()
    def stop(self) -> None:
        self._stop_requested = True
        try:
            if self._process is not None and hasattr(self._process, "stop_the_process"):
                self._process.stop_the_process()
        except Exception:
            pass


class SprkkrRunWindow(QDialog):
    def __init__(
        self,
        atoms: Any = None,
        input_parameters: Any = None,
        directory: str | None = None,
        parent: Any | None = None,
        *,
        request: CalculationRequest | None = None,
        structure_gate: StructureAccessGate | None = None,
        on_finished: Callable[[Any], None] | None = None,
        on_activity_started: Callable[[Any], None] | None = None,
        on_activity_ended: Callable[[Any], None] | None = None,
        on_prepared: Callable[[Any], None] | None = None,
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
        self._prepared_callback = on_prepared
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
        self._structure_gate = structure_gate or StructureAccessGate()

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
        worker = _SprkkrRunWorker(request, self._structure_gate)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(self._on_finished)
        if self._activity_started_callback is not None:
            worker.activityStarted.connect(self._activity_started_callback)
        if self._activity_ended_callback is not None:
            worker.activityEnded.connect(self._activity_ended_callback)
        if self._prepared_callback is not None:
            worker.preparationFinished.connect(self._prepared_callback)

        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
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
        if self._worker is not None:
            self._worker.stop()

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        self._append_output(f"\n[ERROR] {message}\n", "stderr")
        self._stop_btn.setEnabled(False)

    @pyqtSlot(object)
    def _on_finished(self, _result: object) -> None:
        try:
            if self._finished_callback is not None:
                self._finished_callback(_result)
        finally:
            self._stop_btn.setEnabled(False)
