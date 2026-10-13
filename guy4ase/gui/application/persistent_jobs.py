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

    @property
    def is_final(self) -> bool:
        return self.state in _FINAL_STATES

    @classmethod
    def from_run_record(cls, record: Any) -> "PersistentJob":
        artifacts = getattr(record, "artifacts", None)
        artifact_state = (
            _value(getattr(artifacts, "state", None)) if artifacts is not None else None
        )
        return cls(
            id=str(record.id),
            state=_value(record.state),
            created_at=str(record.created_at),
            updated_at=str(record.updated_at),
            task=str(record.task).upper(),
            directory=str(record.directory),
            dataset=(None if record.dataset is None else str(record.dataset)),
            target=_execution_target(record),
            return_code=getattr(record, "return_code", None),
            message=getattr(record, "message", None),
            artifact_state=artifact_state or None,
        )


class PersistentJobSource:
    """Adapter over the evolving ASE2SPRKKR persistent execution API.

    The released Guy4ASE-compatible ASE2SPRKKR branch may temporarily lack this
    API. In that case the adapter intentionally behaves as an empty source. The
    GUI stays usable and the integration becomes active automatically once the
    execution manager API is present.
    """

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

    def load_result(self, job_id: str) -> Any:
        if not self.supports_results:
            raise NotImplementedError(
                "This ASE2SPRKKR version cannot load persistent historical results."
            )
        return self._manager.load_result(job_id)
