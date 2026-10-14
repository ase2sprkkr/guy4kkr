"""Tests for the persistent ASE2SPRKKR run-history source."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import (
    PersistentJob,
    PersistentJobSource,
)


class _State(str, Enum):
    RUNNING = "running"
    FINISHING = "finishing"
    FINISHED = "finished"


class _ResultFilesState(str, Enum):
    CURRENT = "current"
    OVERWRITTEN = "overwritten"


def _record(
    *,
    state=_State.RUNNING,
    endpoint=None,
    reference=None,
    finished_at=None,
    result_files=None,
):
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
        return_code=0 if state == _State.FINISHED else None,
        message="queued remotely",
        result_files=(
            result_files
            if result_files is not None
            else SimpleNamespace(state=_ResultFilesState.CURRENT)
        ),
    )


class _Store:
    def __init__(self, record):
        self.record = record
        self.runs_calls = 0
        self.get_calls = []

    def runs(self):
        self.runs_calls += 1
        return (self.record,)

    def get(self, job_id):
        self.get_calls.append(job_id)
        if job_id != self.record.id:
            raise FileNotFoundError(job_id)
        return self.record


class _Manager:
    def __init__(self, record):
        self.store = _Store(record)
        self.refresh_calls = 0
        self.attach_calls = []
        self.attach_callbacks = {}
        self.runner = object()
        self.loaded_result = None
        self.checked_record = record

    def refresh(self):
        self.refresh_calls += 1

    def attach(self, job_id, *, callback=None, output_listener=None):
        self.attach_calls.append((job_id, output_listener))
        self.attach_callbacks[job_id] = callback
        return self.runner

    def load_result(self, job_id):
        if self.loaded_result is None:
            self.loaded_result = SimpleNamespace(
                run_record=self.store.get(job_id)
            )
        return self.loaded_result

    def check_result_files(self, job_id):
        assert job_id == self.store.record.id
        return self.checked_record


def _endpoint(executor="local", *, host=None, psij_backend=None):
    return SimpleNamespace(
        executor=executor,
        host=host,
        psij_backend=psij_backend,
    )


def _reference(
    executor="local",
    *,
    native_id="1234567890abcdef",
    computer=None,
):
    return SimpleNamespace(
        executor=executor,
        native_id=native_id,
        computer=computer,
    )


def test_persistent_job_maps_endpoint_metadata():
    record = _record(
        endpoint=_endpoint(
            "ssh",
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
    assert not job.attachable


def test_persistent_job_maps_finished_at_independently_of_updated_at():
    record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T06:20:00+00:00",
    )
    record.updated_at = "2026-10-13T08:45:00+00:00"

    job = PersistentJob.from_run_record(record)

    assert job.finished_at == "2026-10-13T06:20:00+00:00"
    assert job.updated_at == "2026-10-13T08:45:00+00:00"


def test_active_reconnectable_job_is_attachable():
    job = PersistentJob.from_run_record(
        _record(endpoint=_endpoint(), reference=_reference())
    )
    assert job.attachable


def test_legacy_pid_only_local_job_is_not_attachable():
    job = PersistentJob.from_run_record(
        _record(
            endpoint=_endpoint(),
            reference=_reference(native_id="12345"),
        )
    )
    assert not job.attachable


def test_active_legacy_job_without_endpoint_is_not_attachable_after_restart():
    job = PersistentJob.from_run_record(
        _record(
            reference=_reference(
                "remote:local",
                native_id="backend-id",
                computer="cluster.example",
            )
        )
    )
    assert not job.attachable


def test_source_caches_store_and_refresh_reloads_metadata():
    running = _record()
    manager = _Manager(running)
    source = PersistentJobSource(manager)

    assert manager.store.runs_calls == 1
    assert source.jobs()[0].state == "running"

    manager.store.record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
    )
    jobs = source.refresh()

    assert manager.refresh_calls == 1
    assert manager.store.runs_calls == 2
    assert jobs[0].state == "finished"


def test_job_changed_rereads_authoritative_store_and_emits_id():
    manager = _Manager(_record())
    source = PersistentJobSource(manager)
    changed = []
    source.changed.connect(changed.append)

    manager.store.record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
    )
    updated = source.job_changed(manager.store.record.id)

    assert manager.store.get_calls == [manager.store.record.id]
    assert updated is not None and updated.state == "finished"
    assert source.job(manager.store.record.id).state == "finished"
    assert changed == [manager.store.record.id]


def test_source_attach_forwards_output_listener_and_callback():
    record = _record()
    manager = _Manager(record)
    source = PersistentJobSource(manager)
    replay = []
    callback = object()

    runner = source.attach(
        record.id,
        callback=callback,
        output_listener=lambda text, kind: replay.append((text, kind)),
    )

    assert runner is manager.runner
    assert manager.attach_callbacks[record.id] is callback
    assert manager.attach_calls[0][1] is not None


def test_source_owns_finishing_recovery_until_completion():
    finishing = _record(
        state=_State.FINISHING,
        endpoint=_endpoint(),
        reference=_reference(),
    )
    manager = _Manager(finishing)
    source = PersistentJobSource(manager)

    assert source.is_recovering(finishing.id)
    assert [call[0] for call in manager.attach_calls] == [finishing.id]

    manager.store.record = _record(
        state=_State.FINISHED,
        endpoint=_endpoint(),
        reference=_reference(),
        finished_at="2026-10-13T07:00:00+00:00",
    )
    manager.attach_callbacks[finishing.id](object())

    assert not source.is_recovering(finishing.id)


def test_source_handles_synchronous_recovery_completion(_qt_application):
    finishing = _record(
        state=_State.FINISHING,
        endpoint=_endpoint(),
        reference=_reference(),
    )

    class Manager(_Manager):
        def attach(self, job_id, *, callback=None, output_listener=None):
            self.attach_calls.append((job_id, output_listener))
            self.store.record = _record(
                state=_State.FINISHED,
                endpoint=_endpoint(),
                reference=_reference(),
                finished_at="2026-10-13T07:00:00+00:00",
            )
            callback(object())
            return self.runner

    source = PersistentJobSource(Manager(finishing))
    assert not source.is_recovering(finishing.id)
    _qt_application.processEvents()
    assert source.job(finishing.id).state == "finished"


def test_result_file_check_updates_cached_verified_snapshot():
    stored = _record()
    manager = _Manager(stored)
    manager.checked_record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
        result_files=SimpleNamespace(
            state=_ResultFilesState.OVERWRITTEN
        ),
    )
    source = PersistentJobSource(manager)

    verified = source.check_result_files(stored.id)

    assert verified.result_files_state == "overwritten"
    assert verified.result_files_verified
    assert source.job(stored.id) == verified


def test_incomplete_manager_becomes_empty_source():
    source = PersistentJobSource(SimpleNamespace())

    assert not source.available
    assert source.jobs() == ()
    assert source.unavailable_reason is not None


def test_notify_changed_reloads_on_source_qt_thread(_qt_application):
    manager = _Manager(_record())
    source = PersistentJobSource(manager)

    manager.store.record = _record(
        state=_State.FINISHED,
        finished_at="2026-10-13T07:00:00+00:00",
    )
    source.notify_changed(manager.store.record.id)

    assert source.job(manager.store.record.id).state == "running"
    _qt_application.processEvents()
    assert source.job(manager.store.record.id).state == "finished"
