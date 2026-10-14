"""Additional behavioral tests for the observable persistent-job source."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


class _State(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"


class _ResultFilesState(str, Enum):
    CURRENT = "current"


def _record(*, endpoint=None, reference=None, state=_State.RUNNING):
    return SimpleNamespace(
        id="1234567890abcdef",
        state=state,
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
        finished_at=None,
        task="dos",
        directory="/tmp/calc",
        dataset="Fe-DOS",
        endpoint=endpoint,
        reference=reference,
        return_code=None,
        message=None,
        result_files=SimpleNamespace(state=_ResultFilesState.CURRENT),
    )


def test_persistent_job_uses_legacy_reference_when_endpoint_is_missing():
    record = _record(
        state=_State.FINISHED,
        reference=SimpleNamespace(
            executor="slurm",
            computer="login01",
            native_id="42",
        ),
    )

    job = PersistentJob.from_run_record(record)

    assert job.target == "slurm · login01"
    assert job.is_final
    assert not job.attachable


def test_source_attach_forwards_output_listener_and_completion_callback():
    record = _record()
    runner = object()
    seen = []
    completion = object()

    class Store:
        def runs(self): return (record,)
        def get(self, run_id):
            assert run_id == record.id
            return record

    class Manager:
        store = Store()
        def refresh(self): pass
        def load_result(self, *_args, **_kwargs): return SimpleNamespace(run_record=record)
        def check_result_files(self, *_args, **_kwargs): return record
        def attach(self, job_id, *, callback=None, output_listener=None):
            assert job_id == record.id
            assert callback is completion
            output_listener("already written\n", "out")
            return runner

    source = PersistentJobSource(Manager())

    assert source.attach(
        record.id,
        callback=completion,
        output_listener=lambda text, kind: seen.append((text, kind)),
    ) is runner
    assert seen == [("already written\n", "out")]
