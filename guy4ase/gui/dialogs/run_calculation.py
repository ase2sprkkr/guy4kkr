from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from ase2sprkkr.ase.symbols import filename_from_symbols
from ase2sprkkr.execution import (
    ExecutionSpec,
    LocalExecutor,
    RunConflictError,
    RunRegistry,
    TrackingExecutor,
)
from ase2sprkkr.sprkkr.calculator import FilenameTemplator, SPRKKR
from ase2sprkkr.sprkkr.profile import executor_from_profile
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


class _ConflictDecision:
    """One worker-to-GUI conflict decision."""

    def __init__(self) -> None:
        self._event = Event()
        self._proceed = False

    def resolve(self, proceed: bool) -> None:
        self._proceed = bool(proceed)
        self._event.set()

    def wait(self, cancellation: _RunCancellation) -> bool:
        while not self._event.wait(0.1):
            if cancellation.requested:
                return False
        return self._proceed


def _tracking_executor(calculator: SPRKKR, registry: RunRegistry) -> TrackingExecutor:
    """Wrap the executor selected by the resolved calculator profile."""
    executor = calculator.executor
    profile = calculator.profile
    if profile.executor != "local" and isinstance(executor, LocalExecutor):
        executor = executor_from_profile(profile)
    return TrackingExecutor(executor, registry)


def _conflicting_files(error: RunConflictError) -> tuple[str, ...]:
    requested = set(error.target.files)
    shared: set[str] = set()
    for run in error.conflicts:
        shared.update(requested.intersection(run.target.files))
    return tuple(sorted(shared))


def _confirm_run_conflict(parent: QDialog, error: RunConflictError) -> bool:
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("Calculation File Conflict")
    message.setText(
        "Another active calculation owns files that this run would modify."
    )

    details = [f"Execution target: {error.target.location}"]
    files = _conflicting_files(error)
    if files:
        details.extend(("", "Conflicting files:", *files))
    message.setInformativeText("\n".join(details))

    cancel = message.addButton(QMessageBox.StandardButton.Cancel)
    proceed = message.addButton("Run Anyway", QMessageBox.ButtonRole.AcceptRole)
    message.setDefaultButton(cancel)
    message.exec()
    return message.clickedButton() is proceed


class _SprkkrRunWorker(QObject):
    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # LoadedResult
    cancelled = pyqtSignal()
    conflict = pyqtSignal(object, object)  # RunConflictError, _ConflictDecision

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: _RunCancellation | None = None,
        *,
        run_registry: RunRegistry | None = None,
        launch_lock: Lock | None = None,
    ):
        super().__init__()
        self._request = request
        self._run_registry = run_registry or RunRegistry()
        self._launch_lock = launch_lock or Lock()
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

    def _templator(self, calculator: SPRKKR) -> FilenameTemplator:
        parameters = self._request.input_parameters
        return FilenameTemplator(
            calculator,
            lambda: parameters.task_name,
            lambda: filename_from_symbols(self._request.atoms.symbols),
        )

    def _prepare_dataset(
        self,
        calculator: SPRKKR,
        input_template: str,
    ) -> FilenameTemplator:
        """Mirror save_input's DATASET default before collision preflight."""
        templator = self._templator(calculator)
        parameters = self._request.input_parameters
        if not parameters.CONTROL.DATASET.is_set():
            input_name = templator(input_template)
            parameters.CONTROL.DATASET.result = Path(input_name).stem
        return templator

    def _preflight_target(
        self,
        executor: TrackingExecutor,
        output_template: str,
        templator: FilenameTemplator,
    ):
        directory = os.path.abspath(self._request.directory)
        output_file = templator(output_template)
        if not os.path.isabs(output_file):
            output_file = os.path.join(directory, output_file)

        parameters = self._request.input_parameters
        spec = ExecutionSpec(
            argv=(),
            input_file=None,
            output_file=output_file,
            directory=directory,
            output_files=parameters.output_files(directory),
            cache_files=parameters.cache_files(directory),
        )
        return executor.execution_target(spec)

    def _ask_about_conflict(self, error: RunConflictError) -> bool:
        self.status.emit("Waiting for conflict decision…")
        decision = _ConflictDecision()
        self.conflict.emit(error, decision)
        return decision.wait(self._cancellation)

    def _create_and_submit(
        self,
        calculator: SPRKKR,
        executor: TrackingExecutor,
        file_names: tuple[str, str, str],
    ):
        input_file, potential_file, output_file = file_names

        def read_callback(text: str, kind: str) -> None:
            self.output.emit(text, kind)

        runner = calculator.create_run(
            atoms=self._request.atoms,
            input_parameters=self._request.input_parameters,
            directory=self._request.directory,
            input_file=input_file,
            potential_file=potential_file,
            output_file=output_file,
            empty_spheres=False,
            read_callback=read_callback,
            print_output=False,
            executor=executor,
        )
        if not self._cancellation.register(runner):
            runner.cancel()
            return None
        return runner

    def _launch(self, calculator: SPRKKR):
        executor = _tracking_executor(calculator, self._run_registry)
        file_names = self._file_names()
        templator = self._prepare_dataset(calculator, file_names[0])
        target = self._preflight_target(executor, file_names[2], templator)
        allow_conflicts = False

        while not self._cancellation.requested:
            conflict = None
            with self._launch_lock:
                conflicts = self._run_registry.conflicts(target)
                if conflicts and not allow_conflicts:
                    conflict = RunConflictError(target, conflicts)
                else:
                    runner = self._create_and_submit(
                        calculator,
                        executor,
                        file_names,
                    )
                    if runner is None:
                        return None
                    try:
                        runner.submit(allow_conflicts=allow_conflicts)
                    except RunConflictError as exc:
                        # A non-GUI caller sharing this registry may have
                        # reserved the target without taking our launch lock.
                        conflict = exc
                    else:
                        return runner

            if conflict is None:
                return None
            if not self._ask_about_conflict(conflict):
                return None
            allow_conflicts = True

        return None

    @pyqtSlot()
    def run(self) -> None:
        running = False
        try:
            self.status.emit("Preparing calculation…")
            runner = self._launch(SPRKKR())
            if runner is None:
                self._emit_cancelled()
                return

            running = True
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
        except Exception as exc:  # noqa: BLE001 - worker exception boundary
            if running and self._cancellation.requested:
                self._emit_cancelled()
            else:
                logger.exception("SPR-KKR calculation or result loading failed")
                self.error.emit(str(exc))


class SprkkrRunWindow(QDialog):
    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        run_registry: RunRegistry | None = None,
        launch_lock: Lock | None = None,
        on_finished: Callable[[Any], None] | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("SPRKKR Run")
        self.resize(900, 600)

        self._thread: QThread | None = None
        self._worker: _SprkkrRunWorker | None = None
        self._finished_callback = on_finished
        self._run_registry = run_registry or RunRegistry()
        self._launch_lock = launch_lock or Lock()
        self._close_requested = False

        layout = QVBoxLayout(self)

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

    def _start(self, request: CalculationRequest) -> None:
        thread = QThread(self)
        self._cancellation = _RunCancellation()
        worker = _SprkkrRunWorker(
            request,
            self._cancellation,
            run_registry=self._run_registry,
            launch_lock=self._launch_lock,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.status.connect(self._set_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)
        worker.conflict.connect(
            self._on_conflict,
            Qt.ConnectionType.QueuedConnection,
        )

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

    @pyqtSlot(object, object)
    def _on_conflict(
        self,
        error: RunConflictError,
        decision: _ConflictDecision,
    ) -> None:
        if self._close_requested or self._cancellation.requested:
            decision.resolve(False)
            return
        decision.resolve(_confirm_run_conflict(self, error))

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
