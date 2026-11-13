"""Tests for the persistent ASE2SPRKKR run-history adapter."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import (
    PersistentJob,
    PersistentJobRecovery,
    PersistentJobSource,
)


class _State(str, Enum):
    RUNNING = "running"
    FINISHING = "finishing"
    FINISHED = "finished"


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
        artifacts=SimpleNamespace(state=SimpleNamespace(value="current")),
    )


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
    assert job.artifact_state == "current"
    assert job.finished_at is None
    assert not job.is_final
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


def test_active_reconnectable_job_is_attachable():
    record = _record(
        endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
        reference=SimpleNamespace(
            executor="local",
            native_id="1234567890abcdef",
            computer=None,
        ),
    )

    job = PersistentJob.from_run_record(record)

    assert job.attachable


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


def test_source_lists_without_requiring_newest_keyword():
    record = _record()

    class Store:
        def __init__(self):
            self.calls = 0

        def runs(self):
            self.calls += 1
            return (record,)

    store = Store()
    source = PersistentJobSource(SimpleNamespace(store=store))

    jobs = source.jobs()

    assert store.calls == 1
    assert tuple(job.id for job in jobs) == (record.id,)


def test_source_refreshes_then_reloads_metadata():
    record = _record()

    class Store:
        @staticmethod
        def runs():
            return (record,)

    class Manager:
        store = Store()

        def __init__(self):
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1

    manager = Manager()
    source = PersistentJobSource(manager)

    jobs = source.refresh()

    assert manager.refresh_calls == 1
    assert jobs[0].id == record.id


def test_source_attach_forwards_output_listener_atomically():
    record = _record()
    replay = []
    runner = object()

    class Store:
        @staticmethod
        def runs():
            return (record,)

    class Manager:
        store = Store()

        @staticmethod
        def attach(job_id, *, output_listener=None):
            assert job_id == record.id
            assert output_listener is not None
            output_listener("already written\n", "out")
            return runner

    source = PersistentJobSource(Manager())

    assert source.supports_attach
    assert source.attach(
        record.id,
        output_listener=lambda text, kind: replay.append((text, kind)),
    ) is runner
    assert replay == [("already written\n", "out")]


def test_source_attach_forwards_completion_callback():
    record = _record()
    callback = object()
    runner = object()

    class Store:
        @staticmethod
        def runs():
            return (record,)

    class Manager:
        store = Store()

        @staticmethod
        def attach(job_id, *, callback=None, output_listener=None):
            assert job_id == record.id
            assert callback is expected_callback
            return runner

    expected_callback = callback
    source = PersistentJobSource(Manager())

    assert source.attach(record.id, callback=callback) is runner


def _finishing_job():
    return PersistentJob.from_run_record(
        _record(
            state=_State.FINISHING,
            endpoint=SimpleNamespace(executor="local", host=None, psij_backend=None),
            reference=SimpleNamespace(
                executor="local",
                native_id="1234567890abcdef",
                computer=None,
            ),
        )
    )


def test_recovery_retains_finishing_runner_until_completion():
    job = _finishing_job()
    runner = object()
    callbacks = {}

    class Source:
        supports_attach = True

        @staticmethod
        def attach(job_id, *, callback=None, output_listener=None):
            callbacks[job_id] = callback
            return runner

    recovery = PersistentJobRecovery(Source())
    recovery.recover_finishing((job,))

    assert recovery.active_ids == (job.id,)
    callbacks[job.id](object())
    assert recovery.active_ids == ()


def test_recovery_handles_synchronous_completion_without_stale_runner():
    job = _finishing_job()

    class Source:
        supports_attach = True

        @staticmethod
        def attach(job_id, *, callback=None, output_listener=None):
            callback(object())
            return object()

    recovery = PersistentJobRecovery(Source())
    recovery.recover_finishing((job,))

    assert recovery.active_ids == ()


def test_incomplete_manager_becomes_empty_source():
    source = PersistentJobSource(SimpleNamespace())

    assert not source.available
    assert source.jobs() == ()
    assert source.unavailable_reason is not None
