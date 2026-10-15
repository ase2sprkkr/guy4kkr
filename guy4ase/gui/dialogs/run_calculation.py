from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import pyqtSignal, pyqtSlot

from guy4ase.gui.application.execution_cancellation import (
    ExecutionCancelled,
    RunCancellation,
)
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import RunProvenance
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow, RunMonitorWorker


logger = logging.getLogger(__name__)


class _SprkkrRunWorker(RunMonitorWorker):
    """Qt signal adapter around the backend-only :class:`SprkkrExecution`."""

    persistentJobChanged = pyqtSignal(str)

    def __init__(
        self,
        atoms,
        input_parameters,
        directory: str,
        provenance: RunProvenance,
        cancellation: RunCancellation,
        *,
        profile_name: str | None = None,
        execution_manager=None,
    ) -> None:
        super().__init__()
        self._execution = SprkkrExecution(
            atoms,
            input_parameters,
            directory,
            provenance,
            cancellation,
            profile_name=profile_name,
            execution_manager=execution_manager,
            output=self.output.emit,
            status=self.status.emit,
            warning=self.warning.emit,
            persistent_job_changed=self.persistentJobChanged.emit,
        )

    def _emit_cancelled(self) -> None:
        self.status.emit("Cancelled")
        self.cancelled.emit()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self._execution.run())
        except ExecutionCancelled:
            self._emit_cancelled()
        except Exception as exc:  # noqa: BLE001 - worker/backend boundary
            logger.exception("SPR-KKR calculation or result loading failed")
            self.error.emit(str(exc))


class SprkkrRunWindow(RunMonitorWindow):
    """Snapshot one launch and display it in the generic run monitor."""

    persistentJobChanged = pyqtSignal(str)

    def __init__(
        self,
        atoms,
        input_parameters,
        directory: str,
        provenance: RunProvenance,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        on_finished=None,
    ) -> None:
        header = f"Directory: {directory}"
        if profile_description:
            header = f"{header}\n{profile_description}"

        # The window is the launch boundary. From here on the calculation owns
        # detached mutable inputs even if the workspace changes before the
        # worker actually runs.
        self._atoms = atoms.copy()
        self._input_parameters = input_parameters.copy(copy_values=True)
        self._directory = directory
        self._provenance = provenance
        self._execution_manager = None

        def worker_factory(cancellation: RunCancellation) -> _SprkkrRunWorker:
            worker = _SprkkrRunWorker(
                self._atoms,
                self._input_parameters,
                self._directory,
                self._provenance,
                cancellation,
                profile_name=profile_name,
                execution_manager=self._execution_manager,
            )
            worker.persistentJobChanged.connect(self._persistent_job_changed_received)
            return worker

        # Ownership and execution context are established by the caller before
        # ``start()``. This prevents a fast local submit from publishing a run id
        # before the application owns this top-level window.
        super().__init__(
            worker_factory,
            parent,
            title="SPRKKR Run",
            header=header,
            warning_title="MPI Not Detected",
            on_finished=on_finished,
            autostart=False,
        )

    def set_execution_manager(self, manager) -> None:
        """Capture persistent execution context before this monitor is started."""
        if self._thread is not None:
            raise RuntimeError("execution context cannot change after the run has started")
        self._execution_manager = manager

    @pyqtSlot(str)
    def _persistent_job_changed_received(self, job_id: str) -> None:
        self.persistentJobChanged.emit(job_id)
