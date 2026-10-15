from types import SimpleNamespace

import guy4ase.gui.application.persistent_jobs as persistent_jobs_module
from guy4ase.gui.application.persistent_jobs import PersistentJobSource


def _record(state):
    return SimpleNamespace(
        id="run-1",
        state=state,
        created_at="2026-10-15T12:00:00+00:00",
        updated_at="2026-10-15T12:05:00+00:00",
        finished_at=None,
        task="DOS",
        directory="/tmp/calc",
        dataset="case",
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local", native_id="run-1", computer=None
        ),
        return_code=0,
        message=None,
        result_files=None,
    )


class _Store:
    def __init__(self, record):
        self.record = record

    def runs(self):
        return (self.record,)

    def get(self, job_id):
        assert job_id == self.record.id
        return self.record


class _Manager:
    def __init__(self, record):
        self.store = _Store(record)

    def attach(self, *_args, **_kwargs):
        raise AssertionError("task-aware attach boundary must be used")

    def retry_finalization(self, record):
        return record


def test_deterministic_recovery_failure_refreshes_terminal_state(monkeypatch):
    manager = _Manager(_record("finalizing"))
    calls = []

    def attach(_manager, job_id, **_kwargs):
        calls.append(job_id)
        manager.store.record = _record("finalization_failed")
        manager.store.record.finished_at = "2026-10-15T12:06:00+00:00"
        manager.store.record.message = "unknown persisted task"
        raise RuntimeError("unknown persisted task")

    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)

    source = PersistentJobSource(manager)

    assert calls == ["run-1"]
    assert source.active_recovery_ids == ()
    assert source.job("run-1").state == "finalization_failed"
    assert source.job("run-1").message == "unknown persisted task"


def test_transient_recovery_failure_stays_finalizing_without_recursive_retry(monkeypatch):
    manager = _Manager(_record("finalizing"))
    calls = []

    def attach(_manager, job_id, **_kwargs):
        calls.append(job_id)
        raise OSError("temporary ssh failure")

    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)

    source = PersistentJobSource(manager)

    assert calls == ["run-1"]
    assert source.active_recovery_ids == ()
    assert source.job("run-1").state == "finalizing"
