"""Tests for the persistent ASE2SPRKKR run-history source."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

import pytest

import guy4ase.gui.application.persistent_jobs as persistent_jobs_module
from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


class _State(str, Enum):
    RUNNING = "running"
    FINALIZING = "finalizing"
    FINISHED = "finished"
    EXECUTION_FAILED = "execution_failed"
    FINALIZATION_FAILED = "finalization_failed"


def _record(*, state=_State.RUNNING, endpoint=None, reference=None, finished_at=None):
    return SimpleNamespace(
        id="1234567890abcdef",
        state=state,
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
        finished_at=finished_at,
        task="dos",
        directory="/tmp/calc",
        dataset="Fe-DOS",
        endpoint=endpoint,
        reference=reference,
        return_code=None,
        message="queued remotely",
        result_files=SimpleNamespace(state=SimpleNamespace(value="current")),
    )


def _finalizing_record():
    return _record(
        state=_State.FINALIZING,
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="1234567890abcdef",
            computer=None,
        ),
    )


def _finalization_failed_record():
    return _record(
        state=_State.FINALIZATION_FAILED,
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="1234567890abcdef",
            computer=None,
        ),
        finished_at="2026-10-13T06:40:00+00:00",
    )


class _Store:
    def __init__(self, records=()):
        self.records = {str(record.id): record for record in records}
        self.runs_calls = 0
        self.get_calls = []

    def runs(self):
        self.runs_calls += 1
        return tuple(self.records.values())

    def get(self, job_id):
        self.get_calls.append(job_id)
        try:
            return self.records[str(job_id)]
        except KeyError as exc:
            raise FileNotFoundError(job_id) from exc


def test_persistent_job_maps_endpoint_metadata():
    record = _record(
        endpoint=SimpleNamespace(
            executor="ssh",
            host="cluster.example",
            psij_backend="slurm",
        )
    )
    job = PersistentJob.from_run_record(record)

    assert job.state == "running"
    assert job.task == "DOS"
    assert job.target == "SSH · cluster.example · PSI/J slurm"
    assert job.result_files_state == "current"
    assert job.finished_at is None
    assert not job.is_final
    assert not job.can_retry_finalization
    assert not job.attachable


def test_persistent_job_maps_stable_finished_at_independently_of_updated_at():
    record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T06:20:00+00:00",
    )
    record.updated_at = "2026-10-13T08:45:00+00:00"
    job = PersistentJob.from_run_record(record)

    assert job.finished_at == "2026-10-13T06:20:00+00:00"
    assert job.updated_at == "2026-10-13T08:45:00+00:00"


@pytest.mark.parametrize(
    "state",
    (_State.FINISHED, _State.EXECUTION_FAILED, _State.FINALIZATION_FAILED),
)
def test_terminal_states_are_not_attachable(state):
    record = _record(
        state=state,
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="1234567890abcdef",
            computer=None,
        ),
    )
    job = PersistentJob.from_run_record(record)

    assert job.is_final
    assert not job.attachable
    assert job.can_retry_finalization is (state is _State.FINALIZATION_FAILED)


def test_active_reconnectable_job_is_attachable():
    record = _record(
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="1234567890abcdef",
            computer=None,
        ),
    )
    assert PersistentJob.from_run_record(record).attachable


def test_legacy_pid_only_local_job_is_not_attachable():
    record = _record(
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="12345",
            computer=None,
        ),
    )
    assert not PersistentJob.from_run_record(record).attachable


def test_active_legacy_job_without_endpoint_is_not_attachable_after_restart():
    record = _record(
        reference=SimpleNamespace(
            executor="remote:local",
            native_id="backend-id",
            computer="cluster.example",
        )
    )
    assert not PersistentJob.from_run_record(record).attachable


def test_persistent_job_uses_legacy_reference_when_endpoint_is_missing():
    record = _record(
        state=_State.FINISHED,
        reference=SimpleNamespace(executor="slurm", computer="login01", native_id="42"),
    )
    job = PersistentJob.from_run_record(record)

    assert job.target == "slurm · login01"
    assert job.is_final
    assert not job.attachable


def test_source_initial_load_populates_cache_once():
    record = _record()
    store = _Store((record,))
    source = PersistentJobSource(SimpleNamespace(store=store))

    assert store.runs_calls == 1
    assert tuple(job.id for job in source.jobs()) == (record.id,)
    assert source.jobs()[0] is source.job(record.id)
    assert store.runs_calls == 1


def test_job_changed_reloads_one_authoritative_record_and_notifies():
    record = _record()
    store = _Store((record,))
    source = PersistentJobSource(SimpleNamespace(store=store))
    changes = []
    source.subscribe(changes.append)

    updated = _record(state=_State.FINISHED, finished_at="2026-10-13T07:00:00+00:00")
    updated.updated_at = "2026-10-13T07:00:00+00:00"
    store.records[record.id] = updated

    job = source.job_changed(record.id)

    assert store.get_calls == [record.id]
    assert job is source.job(record.id)
    assert job.state == "finished"
    assert changes == [record.id]


def test_source_refreshes_backend_then_reloads_metadata():
    record = _record()
    store = _Store((record,))

    class Manager:
        def __init__(self):
            self.store = store
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            updated = _record(
                state=_State.FINISHED,
                finished_at="2026-10-13T07:00:00+00:00",
            )
            updated.updated_at = "2026-10-13T07:00:00+00:00"
            self.store.records[updated.id] = updated

    manager = Manager()
    source = PersistentJobSource(manager)
    changes = []
    source.subscribe(changes.append)

    jobs = source.refresh()

    assert manager.refresh_calls == 1
    assert jobs[0].state == "finished"
    assert changes == [record.id]


def test_source_attach_uses_persistent_boundary_atomically(monkeypatch):
    record = _record()
    store = _Store((record,))
    replay = []
    runner = object()
    calls = []

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            raise AssertionError("source must use the task-aware attach boundary")

    def attach(manager, job_id, *, callback=None, output_listener=None):
        calls.append((manager, job_id, callback, output_listener))
        output_listener("already written\n", "out")
        return runner

    manager = Manager()
    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)
    source = PersistentJobSource(manager)
    listener = lambda text, kind: replay.append((text, kind))

    assert source.attach(record.id, output_listener=listener) is runner
    assert replay == [("already written\n", "out")]
    assert calls == [(manager, record.id, None, listener)]


def test_source_owns_finalizing_recovery_until_completion(monkeypatch):
    record = _finalizing_record()
    store = _Store((record,))
    callbacks = {}
    runner = object()

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            raise AssertionError("source must use the task-aware attach boundary")

    def attach(_manager, job_id, *, callback=None, output_listener=None):
        callbacks[job_id] = callback
        return runner

    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)
    source = PersistentJobSource(Manager())

    assert source.active_recovery_ids == (record.id,)
    finished = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
    )
    finished.updated_at = "2026-10-13T07:00:00+00:00"
    store.records[record.id] = finished
    callbacks[record.id](object())

    assert source.active_recovery_ids == ()
    assert source.job(record.id).state == "finished"
    assert store.get_calls == [record.id]


def test_finalization_failed_is_not_automatically_recovered(monkeypatch):
    record = _finalization_failed_record()
    store = _Store((record,))

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            raise AssertionError("terminal finalization failure must not auto-attach")

        @staticmethod
        def retry_finalization(*_args, **_kwargs):
            raise AssertionError("retry must be explicit")

    monkeypatch.setattr(
        persistent_jobs_module,
        "attach_persistent_run",
        lambda *_args, **_kwargs: pytest.fail("retry must be explicit"),
    )
    source = PersistentJobSource(Manager())

    job = source.job(record.id)
    assert job.is_final
    assert job.can_retry_finalization
    assert not job.attachable
    assert source.supports_retry_finalization
    assert source.active_recovery_ids == ()


def test_explicit_finalization_retry_uses_same_attach_boundary(monkeypatch):
    record = _finalization_failed_record()
    store = _Store((record,))
    runner = object()
    calls = []

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            pass

        @staticmethod
        def retry_finalization(*_args, **_kwargs):
            pass

    def attach(manager, job_id, *, callback=None, output_listener=None):
        calls.append((manager, job_id, callback, output_listener))
        return runner

    manager = Manager()
    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)
    source = PersistentJobSource(manager)

    assert source.attach(record.id) is runner
    assert calls == [(manager, record.id, None, None)]


def test_source_recovery_handles_synchronous_completion_without_stale_runner(monkeypatch):
    record = _finalizing_record()
    finished = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
    )
    store = _Store((record,))

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            raise AssertionError("source must use the task-aware attach boundary")

    def attach(_manager, job_id, *, callback=None, output_listener=None):
        store.records[job_id] = finished
        callback(object())
        return object()

    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)
    source = PersistentJobSource(Manager())

    assert source.active_recovery_ids == ()
    assert source.job(record.id).state == "finished"


def test_recovery_completion_does_not_propagate_metadata_refresh_failure(monkeypatch):
    record = _finalizing_record()
    callbacks = {}

    class Store(_Store):
        def get(self, job_id):
            raise OSError("metadata temporarily unavailable")

    store = Store((record,))

    class Manager:
        def __init__(self):
            self.store = store

        @staticmethod
        def attach(*_args, **_kwargs):
            raise AssertionError("source must use the task-aware attach boundary")

    def attach(_manager, job_id, *, callback=None, output_listener=None):
        callbacks[job_id] = callback
        return object()

    monkeypatch.setattr(persistent_jobs_module, "attach_persistent_run", attach)
    source = PersistentJobSource(Manager())

    callbacks[record.id](object())

    assert source.active_recovery_ids == ()
    assert source.job(record.id).state == "finalizing"


def test_explicit_manager_must_satisfy_run_store_contract():
    with pytest.raises(TypeError, match="run store"):
        PersistentJobSource(SimpleNamespace())
