"""Attach an existing persistent run to the generic run monitor."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget

from guy4ase.gui.application.execution_cancellation import RunCancellation
from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow, state_label


logger = logging.getLogger(__name__)


class AttachedRunWorker(QObject):
    """Attach/wait orchestration for an existing persistent calculation."""

    output = pyqtSignal(str, str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(
        self,
        source: PersistentJobSource,
        job_id: str,
        cancellation: RunCancellation,
    ) -> None:
        super().__init__()
        self._source = source
        self._job_id = job_id
        self._cancellation = cancellation

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

            runner = self._source.attach(
                self._job_id,
                output_listener=output_listener,
            )
            if not self._cancellation.register(runner):
                runner.cancel()
                self._emit_cancelled()
                return

            attached = True
            self.status.emit(state_label(runner.state))
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
                logger.exception("Failed to attach to SPR-KKR calculation")
                self.error.emit(str(exc))


def create_attached_run_monitor(
    job: PersistentJob,
    source: PersistentJobSource,
    parent: QWidget | None = None,
    *,
    on_finished: Callable[[Any], None] | None = None,
) -> RunMonitorWindow:
    """Create the generic monitor configured for an existing persistent job."""
    title = job.dataset or job.id
    return RunMonitorWindow(
        lambda cancellation: AttachedRunWorker(source, job.id, cancellation),
        parent,
        title=f"Monitor {job.task or 'SPRKKR'} Calculation",
        header=f"{title}\n{job.target} · {job.directory}",
        initial_status=state_label(job.state),
        on_finished=on_finished,
    )
