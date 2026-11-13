from __future__ import annotations

import logging
from threading import Thread
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from guy4ase.gui.application.sprkkr_execution import (
    ExecutionCancelled,
    SprkkrExecution,
)
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs.run_monitor import RunCancellation, RunMonitorWindow


logger = logging.getLogger(__name__)


class _SprkkrRunWorker(QObject):
    """Qt signal adapter around the backend-only :class:`SprkkrExecution`."""

    output = pyqtSignal(str, str)  # (text, kind)
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: RunCancellation | None = None,
        *,
        profile_name: str | None = None,
    ) -> None:
        super().__init__()
        self._cancellation = cancellation or RunCancellation()
        self._execution = SprkkrExecution(
            request,
            self._cancellation,
            profile_name=profile_name,
            output=self.output.emit,
            status=self.status.emit,
            warning=self.warning.emit,
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
    """Create an SPR-KKR runner and display it in the generic run monitor."""

    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        on_finished=None,
    ) -> None:
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
