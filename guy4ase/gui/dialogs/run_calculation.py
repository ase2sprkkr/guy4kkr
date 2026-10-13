from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import replace
from threading import Thread
from typing import Any

from ase2sprkkr.execution import MpiNotFoundWarning
from ase2sprkkr.sprkkr.calculator import SPRKKR
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from guy4ase.gui.application.result_loading import load_result
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs.run_monitor import RunCancellation, RunMonitorWindow
from guy4ase.gui.widgets.input_parameters.dataset import (
    dataset_value,
    filename_component,
)


logger = logging.getLogger(__name__)


def _execution_request(request: CalculationRequest) -> CalculationRequest:
    """Return a request whose atoms can be mutated freely by ASE2SPRKKR.

    Worker construction happens on the GUI thread, before the QObject is moved to
    its QThread. Copying here therefore creates the thread boundary explicitly:
    lazy promotion, site initialization and other backend bookkeeping can mutate
    the execution copy without touching the authoritative workspace structure.
    """
    copier = getattr(request.atoms, "copy", None)
    if not callable(copier):
        # CalculationRequest is also used by small unit-test doubles. Real
        # calculation atoms are ASE Atoms and always provide copy().
        return request
    return replace(request, atoms=copier())


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
        cancellation: RunCancellation | None = None,
        *,
        profile_name: str | None = None,
    ):
        super().__init__()
        self._request = _execution_request(request)
        self._profile_name = profile_name
        self._cancellation = cancellation or RunCancellation()

    def _emit_cancelled(self) -> None:
        self.status.emit("Cancelled")
        self.cancelled.emit()

    def _file_names(self) -> tuple[str, str, str]:
        dataset = dataset_value(self._request.input_parameters)
        if dataset is None:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        base = filename_component(dataset)
        if not base:
            return "%a_%T.inp", "%a.pot", "%a_%T.out"
        return f"{base}_%T.inp", f"{base}.pot", f"{base}_%T.out"

    def _with_mpi_warnings(self, operation):
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
            persistent=True,
            restart_scf=self._request.restart_scf,
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
                persistent_ref=runner.id,
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


class SprkkrRunWindow(RunMonitorWindow):
    """Create an SPR-KKR runner and display it in the generic run monitor."""

    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        on_finished=None,
    ):
        header = f"Directory: {request.directory}"
        if profile_description:
            header = f"{header}\n{profile_description}"
        super().__init__(
            lambda cancellation: _SprkkrRunWorker(
                request,
                cancellation,
                profile_name=profile_name,
            ),
            parent,
            title="SPRKKR Run",
            header=header,
            warning_title="MPI Not Detected",
            background_thread_factory=lambda **kwargs: Thread(**kwargs),
            on_finished=on_finished,
        )

    @pyqtSlot(str)
    def _on_warning(self, message: str) -> None:
        QMessageBox.warning(self, "MPI Not Detected", message)
