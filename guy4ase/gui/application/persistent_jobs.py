"""Read and track ASE2SPRKKR persistent-run history behind a GUI-facing API."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

logger = logging.getLogger(__name__)

_FINAL_STATES = frozenset({"finished", "failed", "cancelled"})
JobChangedListener = Callable[[str], None]
_RECOVERING = object()


def _value(value: Any) -> str:
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _execution_target(record: Any) -> str:
    endpoint = getattr(record, "endpoint", None)
    if endpoint is not None:
        executor = _value(getattr(endpoint, "executor", "local")) or "local"
        host = _value(getattr(endpoint, "host", None))
        psij_backend = _value(getattr(endpoint, "psij_backend", None))
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

    reference = getattr(record, "reference", None)
    if reference is not None:
        executor = _value(getattr(reference, "executor", None)) or "Remote"
        computer = _value(getattr(reference, "computer", None))
        return f"{executor} · {computer}" if computer else executor
    return "Unknown"


def _is_attachable(record: Any, state: str) -> bool:
    if state in _FINAL_STATES:
        return False
    if getattr(record, "endpoint", None) is None:
        return False
    reference = getattr(record, "reference", None)
    if reference is None:
        return False
    executor = _value(getattr(reference, "executor", None))
    native_id = _value(getattr(reference, "native_id", None))
    if executor == "local" and native_id != str(record.id):
        return False
    return True


@dataclass(frozen=True)
class PersistentJob:
    """Stable presentation model for one persistent ASE2SPRKKR run."""

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
            _value(getattr(result_files, "state", None))
            if result_files is not None
            else None
        )
        state = _value(record.state)
        finished_at = getattr(record, "finished_at", None)
        return cls(
            id=str(record.id),
            state=state,
            created_at=str(record.created_at),
            updated_at=str(record.updated_at),
            task=str(record.task).upper(),
            directory=str(record.directory),
            dataset=(None if record.dataset is None else str(record.dataset)),
            target=_execution_target(record),
            return_code=getattr(record, "return_code", None),
            message=getattr(record, "message", None),
            result_files_state=result_files_state or None,
            finished_at=None if finished_at is None else str(finished_at),
            attachable=_is_attachable(record, state),
            result_files_verified=result_files_verified,
        )


class PersistentJobSource:
    """Application-owned persistent-job cache and lifecycle adapter.

    ASE2SPRKKR's persisted ``RunRecord`` remains authoritative. ``job_changed``
    receives only a stable run id and reloads the record from the persistent
    store instead of accepting a parallel copy of lifecycle state.

    Recovery of persisted ``finishing`` jobs is an implementation detail of
    this source. Presentation code never owns or drives recovery.
    """

    def __init__(self, manager: Any | None = None) -> None:
        self._manager = manager
        self.unavailable_reason: str | None = None
        self._lock = RLock()
        self._jobs: dict[str, PersistentJob] = {}
        self._listeners: set[JobChangedListener] = set()
        self._recovery_runners: dict[str, Any] = {}

        if manager is None:
            try:
                from ase2sprkkr.execution import ExecutionManager
            except ImportError:
                self.unavailable_reason = (
                    "Persistent calculation history is not available in this "
                    "ASE2SPRKKR version yet."
                )
                return
            manager = ExecutionManager()
            self._manager = manager

        try:
            store = manager.store
        except AttributeError as exc:
            raise TypeError("persistent job manager must expose a run store") from exc
        if not callable(getattr(store, "runs", None)) or not callable(
            getattr(store, "get", None)
        ):
            raise TypeError("persistent run store must provide runs() and get()")

        self.reload(notify=False)

    @property
    def available(self) -> bool:
        return self._manager is not None

    @property
    def supports_refresh(self) -> bool:
        return self.available and callable(getattr(self._manager, "refresh", None))

    @property
    def supports_results(self) -> bool:
        return self.available and callable(getattr(self._manager, "load_result", None))

    @property
    def supports_attach(self) -> bool:
        return self.available and callable(getattr(self._manager, "attach", None))

    @property
    def supports_result_file_check(self) -> bool:
        return self.available and callable(
            getattr(self._manager, "check_result_files", None)
        )

    @property
    def active_recovery_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._recovery_runners)

    def subscribe(self, listener: JobChangedListener) -> Callable[[], None]:
        """Subscribe to metadata changes and return an unsubscribe callback."""
        with self._lock:
            self._listeners.add(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def _notify(self, job_id: str) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(job_id)
            except Exception:  # noqa: BLE001 - subscriber isolation boundary
                logger.exception("Persistent-job listener failed for %s", job_id)

    def jobs(self) -> tuple[PersistentJob, ...]:
        """Return cached history without backend or filesystem I/O."""
        with self._lock:
            jobs = tuple(self._jobs.values())
        return tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))

    def job(self, job_id: str) -> PersistentJob | None:
        with self._lock:
            return self._jobs.get(str(job_id))

    def reload(self, *, notify: bool = True) -> tuple[PersistentJob, ...]:
        """Reload persisted metadata and recover unfinished finalization."""
        if self._manager is None:
            return ()
        records = self._manager.store.runs()
        loaded = {
            str(record.id): PersistentJob.from_run_record(record)
            for record in records
        }
        with self._lock:
            previous = self._jobs
            self._jobs = loaded
        changed = tuple(
            job_id
            for job_id in set(previous) | set(loaded)
            if previous.get(job_id) != loaded.get(job_id)
        )
        self._recover_finishing(tuple(loaded.values()))
        if notify:
            for job_id in changed:
                self._notify(job_id)
        return self.jobs()

    def job_changed(self, job_id: str) -> PersistentJob | None:
        """Reload one authoritative record after an external lifecycle event."""
        if self._manager is None:
            return None
        job_id = str(job_id)
        try:
            record = self._manager.store.get(job_id)
        except FileNotFoundError:
            with self._lock:
                existed = self._jobs.pop(job_id, None) is not None
            if existed:
                self._notify(job_id)
            return None

        job = PersistentJob.from_run_record(record)
        changed = self._replace_cached_job(job)
        self._recover_finishing((job,))
        if changed:
            self._notify(job_id)
        return job

    def refresh(self) -> tuple[PersistentJob, ...]:
        """Refresh backend state and then reload persisted metadata."""
        if self._manager is None:
            return ()
        if self.supports_refresh:
            self._manager.refresh()
        return self.reload()

    def check_result_files(self, job_id: str) -> PersistentJob:
        if not self.supports_result_file_check:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot verify persistent result files."
            )
        record = self._manager.check_result_files(job_id)
        job = PersistentJob.from_run_record(record, result_files_verified=True)
        if self._replace_cached_job(job):
            self._notify(job.id)
        return job

    def attach(
        self,
        job_id: str,
        *,
        callback=None,
        output_listener=None,
    ) -> Any:
        """Reconnect to an active run for an explicit user monitor."""
        if not self.supports_attach:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot attach to persistent calculations."
            )
        kwargs = {"output_listener": output_listener}
        if callback is not None:
            kwargs["callback"] = callback
        return self._manager.attach(job_id, **kwargs)

    def load_result(self, job_id: str) -> Any:
        if not self.supports_results:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot load persistent historical results."
            )
        result = self._manager.load_result(job_id)
        record = getattr(result, "run_record", None)
        if record is not None:
            job = PersistentJob.from_run_record(record, result_files_verified=True)
            if self._replace_cached_job(job):
                self._notify(job.id)
        return result

    def _replace_cached_job(self, job: PersistentJob) -> bool:
        with self._lock:
            previous = self._jobs.get(job.id)
            self._jobs[job.id] = job
        return previous != job

    def _recover_finishing(self, jobs: tuple[PersistentJob, ...]) -> None:
        if not self.supports_attach:
            return
        for job in jobs:
            if job.state != "finishing" or not job.attachable:
                continue
            try:
                self._recover(job.id)
            except Exception:  # noqa: BLE001 - persisted/backend recovery boundary
                logger.exception("Failed to recover persistent run %s", job.id)

    def _recover(self, job_id: str) -> Any | None:
        # Reserve the identity before attach, then release the lock. A second
        # reload sees the sentinel and cannot attach the same finishing run.
        with self._lock:
            if job_id in self._recovery_runners:
                value = self._recovery_runners[job_id]
                return None if value is _RECOVERING else value
            self._recovery_runners[job_id] = _RECOVERING

        completed_synchronously = False

        def completed(_result: Any) -> None:
            nonlocal completed_synchronously
            completed_synchronously = True
            with self._lock:
                self._recovery_runners.pop(job_id, None)
            try:
                self.job_changed(job_id)
            except Exception:  # noqa: BLE001 - recovery completion boundary
                logger.exception(
                    "Recovered persistent run %s completed, but its metadata "
                    "could not be refreshed",
                    job_id,
                )

        try:
            runner = self.attach(job_id, callback=completed)
        except BaseException:
            with self._lock:
                if self._recovery_runners.get(job_id) is _RECOVERING:
                    self._recovery_runners.pop(job_id, None)
            raise

        with self._lock:
            if completed_synchronously or job_id not in self._recovery_runners:
                return None
            self._recovery_runners[job_id] = runner
        return runner
