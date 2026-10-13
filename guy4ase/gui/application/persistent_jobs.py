"""Read ASE2SPRKKR persistent-run history behind a small GUI-facing API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

    # A fresh ExecutionManager can reconstruct only persisted endpoints. Old
    # records with a backend reference but no endpoint still work inside the
    # process that registered their executor, but not after a GUI restart.
    if getattr(record, "endpoint", None) is None:
        return False

    reference = getattr(record, "reference", None)
    if reference is None:
        return False

    # Before reconnectable local execution, local references stored only the
    # subprocess PID. New detached local runs deliberately use the persistent
    # ASE2SPRKKR record id as their backend native id, so this test is exact and
    # does not rely on guessing whether a string merely looks like a PID.
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
    artifact_state: str | None
    attachable: bool = False

    @property
    def started_at(self) -> str:
        """Run start time as represented by ASE2SPRKKR's ``created_at`` field."""
        return self.created_at

    @property
    def is_final(self) -> bool:
        return self.state in _FINAL_STATES

    @classmethod
    def from_run_record(cls, record: Any) -> "PersistentJob":
        artifacts = getattr(record, "artifacts", None)
        artifact_state = (
            _value(getattr(artifacts, "state", None)) if artifacts is not None else None
        )
        state = _value(record.state)
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
            artifact_state=artifact_state or None,
            attachable=_is_attachable(record, state),
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

    def attach(self, job_id: str, *, output_listener=None) -> Any:
        """Reconnect to an active persistent run and replay its output."""
        if not self.supports_attach:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot attach to persistent calculations."
            )
        return self._manager.attach(job_id, output_listener=output_listener)

    def load_result(self, job_id: str) -> Any:
        if not self.supports_results:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot load persistent historical results."
            )
        return self._manager.load_result(job_id)
