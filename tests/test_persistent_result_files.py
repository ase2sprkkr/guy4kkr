"""Result-file freshness checks for persistent calculation history."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


class _State(str, Enum):
    FINISHED = "finished"


class _ResultFilesState(str, Enum):
    CURRENT = "current"
    OVERWRITTEN = "overwritten"


def _record(*, result_files=None):
    return SimpleNamespace(
        id="1234567890abcdef",
        state=_State.FINISHED,
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
        finished_at="2026-10-13T06:20:00+00:00",
        task="dos",
        directory="/tmp/calc",
        dataset="Fe-DOS",
        endpoint=None,
        reference=None,
        return_code=0,
        message=None,
        result_files=result_files,
    )


def test_result_file_state_is_exposed():
    job = PersistentJob.from_run_record(
        _record(result_files=SimpleNamespace(state=_ResultFilesState.OVERWRITTEN))
    )
    assert job.result_files_state == "overwritten"
    assert not job.result_files_verified


def test_explicit_result_file_check_marks_cached_state_as_verified():
    stored = _record(result_files=SimpleNamespace(state=_ResultFilesState.CURRENT))
    checked = _record(result_files=SimpleNamespace(state=_ResultFilesState.OVERWRITTEN))

    class Store:
        def runs(self): return (stored,)
        def get(self, run_id):
            assert run_id == stored.id
            return stored

    class Manager:
        store = Store()
        def refresh(self): pass
        def attach(self, *_args, **_kwargs): return object()
        def load_result(self, *_args, **_kwargs): return SimpleNamespace(run_record=stored)
        def check_result_files(self, run_id):
            assert run_id == stored.id
            return checked

    source = PersistentJobSource(Manager())
    listed = source.jobs()[0]
    verified = source.check_result_files(stored.id)
    assert listed.result_files_state == "current"
    assert not listed.result_files_verified
    assert verified.result_files_state == "overwritten"
    assert verified.result_files_verified
    assert source.job(stored.id) == verified
