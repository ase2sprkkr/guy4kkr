"""Tests for the persistent ASE2SPRKKR run-history adapter."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


class _State(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"


def _record(*, state=_State.RUNNING, endpoint=None, reference=None):
    return SimpleNamespace(
        id="1234567890abcdef",
        state=state,
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
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
    assert not job.is_final


def test_persistent_job_uses_legacy_reference_when_endpoint_is_missing():
    record = _record(
        state=_State.FINISHED,
        reference=SimpleNamespace(executor="slurm", computer="login01"),
    )

    job = PersistentJob.from_run_record(record)

    assert job.target == "slurm · login01"
    assert job.is_final


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


def test_incomplete_manager_becomes_empty_source():
    source = PersistentJobSource(SimpleNamespace())

    assert not source.available
    assert source.jobs() == ()
    assert source.unavailable_reason is not None
