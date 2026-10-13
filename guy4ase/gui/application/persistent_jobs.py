"""Read ASE2SPRKKR persistent-run history behind a small GUI-facing API."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

_FINAL_STATES = frozenset({"finished", "failed", "cancelled"})


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
    """Whether ASE2SPRKKR has enough persisted identity to reattach this run."""
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
        """Run start time as represented by ASE2SPRKKR's ``created_at`` field."""
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
    """Adapter over the ASE2SPRKKR persistent execution API."""

    def __init__(self, manager: Any | None = None) -> None:
        self._manager = manager
        self.unavailable_reason: str | None = None

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

        store = getattr(manager, "store", None)
        if store is None or not callable(getattr(store, "runs", None)):
            self._manager = None
            self.unavailable_reason = (
                "Persistent calculation history is not available in this "
                "ASE2SPRKKR version yet."
            )

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

    def jobs(self) -> tuple[PersistentJob, ...]:
        if self._manager is None:
            return ()
        records = self._manager.store.runs()
        return tuple(PersistentJob.from_run_record(record) for record in records)

    def refresh(self) -> tuple[PersistentJob, ...]:
        """Refresh active backend states when ASE2SPRKKR exposes that operation."""
        if self._manager is None:
            return ()
        if self.supports_refresh:
            self._manager.refresh()
        return self.jobs()

    def check_result_files(self, job_id: str) -> PersistentJob:
        """Explicitly verify freshness for one persisted final calculation."""
        if not self.supports_result_file_check:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot verify persistent result files."
            )
        record = self._manager.check_result_files(job_id)
        return PersistentJob.from_run_record(record, result_files_verified=True)

    def attach(
        self,
        job_id: str,
        *,
        callback=None,
        output_listener=None,
    ) -> Any:
        """Reconnect to an active persistent run."""
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
        return self._manager.load_result(job_id)


class PersistentJobRecovery:
    """Complete persistent lifecycle recovery after a Guy4ASE restart.

    This object has no UI responsibility. It owns attached runners only until
    ASE2SPRKKR finishes stage-out, parsing and persistent finalization.
    """

    def __init__(self, source: PersistentJobSource) -> None:
        self._source = source
        self._runners: dict[str, Any] = {}
        self._lock = RLock()

    @property
    def active_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._runners)

    def recover_finishing(
        self,
        jobs: tuple[PersistentJob, ...],
        *,
        on_completed: Callable[[str, Any], None] | None = None,
    ) -> None:
        if not self._source.supports_attach:
            return
        for job in jobs:
            if job.state == "finishing" and job.attachable:
                self.recover(job.id, on_completed=on_completed)

    def recover(
        self,
        job_id: str,
        *,
        on_completed: Callable[[str, Any], None] | None = None,
    ) -> Any | None:
        """Attach once and retain the runner until its completion callback fires."""
        with self._lock:
            existing = self._runners.get(job_id)
            if existing is not None:
                return existing

            completed_synchronously = False

            def completed(result: Any) -> None:
                nonlocal completed_synchronously
                with self._lock:
                    completed_synchronously = True
                    self._runners.pop(job_id, None)
                if on_completed is not None:
                    on_completed(job_id, result)

            runner = self._source.attach(job_id, callback=completed)
            if completed_synchronously:
                return None
            self._runners[job_id] = runner
            return runner
