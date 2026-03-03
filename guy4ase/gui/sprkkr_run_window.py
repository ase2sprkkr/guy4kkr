from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from ase2sprkkr.sprkkr.calculator import SPRKKR

@dataclass(frozen=True)
class SprkkrRunInputs:
    atoms: Any
    input_parameters: Any
    directory: str


class _SprkkrRunWorker(QObject):
    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # result

    def __init__(self, inputs: SprkkrRunInputs):
        super().__init__()
        self._inputs = inputs
        self._process: Optional[Any] = None
        self._stop_requested = False

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.status.emit("Creating SPRKKR calculator…")

            calc = SPRKKR()

            def read_callback(text: str, kind: str) -> None:
                # Called from the runner while it produces output.
                self.output.emit(text, kind)

            self.status.emit("Preparing calculation…")
            self._process = calc.calculate(
                atoms=self._inputs.atoms,
                input_parameters=self._inputs.input_parameters,
                directory=self._inputs.directory,
                run_async=True,
                read_callback=read_callback,
                print_output=False
            )

            if self._stop_requested:
                raise RuntimeError("Stopped")

            self.status.emit("Running…")
            result = self._process.run()
            self.status.emit("Finished")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    @pyqtSlot()
    def stop(self) -> None:
        self._stop_requested = True
        self._process
        try:
            if self._process is not None and hasattr(self._process, "stop_the_process"):
                self._process.stop_the_process()
        except Exception:
            pass


class SprkkrRunWindow(QDialog):
    def __init__(self, atoms: Any, input_parameters: Any, directory: str, parent: Optional[Any] = None):
        super().__init__(parent)
        self.setWindowTitle("SPRKKR Run")
        self.resize(900, 600)

        self._thread: Optional[QThread] = None
        self._worker: Optional[_SprkkrRunWorker] = None

        layout = QVBoxLayout(self)

        header = QLabel(f"Directory: {directory}")
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

        self._start(SprkkrRunInputs(atoms=atoms, input_parameters=input_parameters, directory=directory))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._on_stop()
        super().closeEvent(event)

    def _start(self, inputs: SprkkrRunInputs) -> None:
        thread = QThread(self)
        worker = _SprkkrRunWorker(inputs)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(self._on_finished)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

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
        self._stop_btn.setEnabled(False)
