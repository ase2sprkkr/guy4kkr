"""Observable access to ASE2SPRKKR persistent-run history."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

from PyQt6.QtCore import QObject, Qt, pyqtSignal

_FINAL_STATES = frozenset({"finished", "failed", "cancelled"})


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    return "" if value is None else str(value)


def _execution_target(record: Any) -> str:
    endpoint = record.endpoint
    if endpoint is not None:
        executor = _value(endpoint.executor) or "local"
        host = _value(endpoint.host)
        psij_backend = _value(endpoint.psij_backend)

        if executor == "local":
            return "Local"
        if executor == "psij":
            return "PSI/J" + (f" · {psij_backend}" if psij_backend else "")

        label = executor.upper() if executor == "ssh" else executor
        if host:
            label = f"{label} · {host}"
        if psij_backend:
            label = f"{label} · PSI/J {psij_backend}"
        return label

    reference = record.reference
    if reference is not None:
        executor = _value(reference.executor) or "Remote"
        computer = _value(reference.computer)
        return f"{executor} · {computer}" if computer else executor
    return "Unknown"


def _is_attachable(record: Any, state: str) -> bool:
    """Whether ASE2SPRKKR has enough persisted identity to reattach this run."""
    if state in _FINAL_STATES or record.endpoint is None or record.reference is None:
        return False

    executor = _value(record.reference.executor)
    native_id = _value(record.reference.native_id)
    if executor == "local" and native_id != str(record.id):
        return False
    return True


@dataclass(frozen=True)
class PersistentJob:
    """Stable GUI presentation model for one persistent ASE2SPRKKR run."""

    id: str
    state: str
    created_at: str
    updated_at: str
    task: str
    directory: str
    dataset: str | None
    target: str
    return_code: int | None
    message: str | None
    result_files_state: str | None = None
    finished_at: str | None = None
    attachable: bool = False
    result_files_verified: bool = False

    @property
    def started_at(self) -> str:
        return self.created_at

    @property
    def is_final(self) -> bool:
        return self.state in _FINAL_STATES

    @classmethod
    def from_run_record(
        cls,
        record: Any,
        *,
        result_files_verified: bool = False,
    ) -> "PersistentJob":
        result_files = record.result_files
        result_files_state = (
            _value(result_files.state) if result_files is not None else None
        )
        state = _value(record.state)
        return cls(
            id=str(record.id),
            state=state,
            created_at=str(record.created_at),
            updated_at=str(record.updated_at),
            task=str(record.task).upper(),
            directory=str(record.directory),
            dataset=None if record.dataset is None else str(record.dataset),
            target=_execution_target(record),
            return_code=record.return_code,
            message=record.message,
            result_files_state=result_files_state or None,
            finished_at=(
                None if record.finished_at is None else str(record.finished_at)
            ),
            attachable=_is_attachable(record, state),
            result_files_verified=result_files_verified,
        )


class PersistentJobSource(QObject):
    """Own the cached persistent-job view and lifecycle recovery.

    ASE2SPRKKR's run store is authoritative. Change notifications carry only
    the stable run id; this source re-reads that record and applies the same
    ``RunRecord -> PersistentJob`` conversion used by full reloads.
    """

    changed = pyqtSignal(str)
    reloaded = pyqtSignal()
    _changeRequested = pyqtSignal(str)

    def __init__(
        self,
        manager: Any | None = None,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._changeRequested.connect(
            self.job_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._lock = RLock()
        self._jobs: dict[str, PersistentJob] = {}
        self._recovery_runners: dict[str, Any] = {}
        self.recovery_error: str | None = None
        self.unavailable_reason: str | None = None

        if manager is None:
            try:
                from ase2sprkkr.execution import ExecutionManager
            except ImportError:
                self._manager = None
                self.unavailable_reason = (
                    "Persistent calculation history is not available in this "
                    "ASE2SPRKKR version yet."
                )
                return
            manager = ExecutionManager()
        try:
            store = manager.store
            required = (
                store.runs,
                store.get,
                manager.refresh,
                manager.attach,
                manager.load_result,
                manager.check_result_files,
            )
        except AttributeError:
            self._manager = None
            self.unavailable_reason = (
                "Persistent calculation history is not available in this "
                "ASE2SPRKKR version yet."
            )
            return
        if not all(callable(operation) for operation in required):
            self._manager = None
            self.unavailable_reason = (
                "Persistent calculation history is not available in this "
                "ASE2SPRKKR version yet."
            )
            return
        self._manager = manager
        self.reload()

    @property
    def available(self) -> bool:
        return self._manager is not None

    @property
    def supports_refresh(self) -> bool:
        return self.available

    @property
    def supports_results(self) -> bool:
        return self.available

    @property
    def supports_attach(self) -> bool:
        return self.available

    @property
    def supports_result_file_check(self) -> bool:
        return self.available

    def jobs(self) -> tuple[PersistentJob, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._jobs.values(),
                    key=lambda job: job.started_at,
                    reverse=True,
                )
            )

    def job(self, job_id: str) -> PersistentJob | None:
        with self._lock:
            return self._jobs.get(str(job_id))

    def is_recovering(self, job_id: str) -> bool:
        with self._lock:
            return str(job_id) in self._recovery_runners

    def reload(self) -> tuple[PersistentJob, ...]:
        """Reload metadata from the persistent store and recover finalization."""
        if self._manager is None:
            with self._lock:
                self._jobs = {}
            self.reloaded.emit()
            return ()

        records = self._manager.store.runs()
        jobs = {
            str(record.id): PersistentJob.from_run_record(record)
            for record in records
        }
        with self._lock:
            self._jobs = jobs
            self.recovery_error = None

        self._recover_finishing(tuple(jobs.values()))
        self.reloaded.emit()
        return self.jobs()

    def refresh(self) -> tuple[PersistentJob, ...]:
        """Refresh active backends, then rebuild the cache from persistent JSON."""
        if self._manager is None:
            return ()
        self._manager.refresh()
        return self.reload()

    def notify_changed(self, job_id: str) -> None:
        """Schedule an authoritative reload of one run on the source's Qt thread.

        This method is safe to call from execution/recovery worker threads. Only
        the stable persistent identity crosses the thread boundary; the source
        reloads the actual state from ASE2SPRKKR's persistent store.
        """
        self._changeRequested.emit(str(job_id))

    def job_changed(self, job_id: str) -> PersistentJob | None:
        """Reload one known persistent identity and publish its new snapshot."""
        if self._manager is None:
            return None
        job_id = str(job_id)
        try:
            record = self._manager.store.get(job_id)
        except FileNotFoundError:
            return None
        job = PersistentJob.from_run_record(record)
        with self._lock:
            self._jobs[job_id] = job
        self._recover_finishing((job,))
        self.changed.emit(job_id)
        return job

    def check_result_files(self, job_id: str) -> PersistentJob:
        """Verify freshness for one final run and publish the refreshed snapshot."""
        if self._manager is None:
            raise NotImplementedError("Persistent calculation history is unavailable.")
        record = self._manager.check_result_files(str(job_id))
        job = PersistentJob.from_run_record(
            record,
            result_files_verified=True,
        )
        with self._lock:
            self._jobs[job.id] = job
        self.changed.emit(job.id)
        return job

    def attach(
        self,
        job_id: str,
        *,
        callback=None,
        output_listener=None,
    ) -> Any:
        """Explicitly attach a caller-owned monitor to a persistent run."""
        if self._manager is None:
            raise NotImplementedError("Persistent calculation history is unavailable.")
        return self._manager.attach(
            str(job_id),
            callback=callback,
            output_listener=output_listener,
        )

    def load_result(self, job_id: str) -> Any:
        """Load a final historical result and publish any metadata side effects."""
        if self._manager is None:
            raise NotImplementedError("Persistent calculation history is unavailable.")
        result = self._manager.load_result(str(job_id))
        record = result.run_record
        job = PersistentJob.from_run_record(
            record,
            result_files_verified=True,
        )
        with self._lock:
            self._jobs[job.id] = job
        self.changed.emit(job.id)
        return result

    def _recover_finishing(self, jobs: tuple[PersistentJob, ...]) -> None:
        for job in jobs:
            if job.state == "finishing" and job.attachable:
                self._recover(job.id)

    def _recover(self, job_id: str) -> Any | None:
        with self._lock:
            existing = self._recovery_runners.get(job_id)
            if existing is not None:
                return existing
            sentinel = object()
            self._recovery_runners[job_id] = sentinel

        def completed(_result: Any) -> None:
            with self._lock:
                self._recovery_runners.pop(job_id, None)
            self.notify_changed(job_id)

        try:
            runner = self.attach(job_id, callback=completed)
        except Exception as exc:  # backend recovery boundary
            with self._lock:
                self._recovery_runners.pop(job_id, None)
                self.recovery_error = str(exc)
            return None

        with self._lock:
            if self._recovery_runners.get(job_id) is sentinel:
                self._recovery_runners[job_id] = runner
                return runner
        return None
