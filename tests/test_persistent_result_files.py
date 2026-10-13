"""Result-file freshness checks for persistent calculation history."""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


class _State(str, Enum):
    FINISHED = "finished"


def _record(*, result_files=None, artifacts=None):
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
        artifacts=artifacts,
    )


def test_result_files_name_is_preferred_over_legacy_artifacts():
    record = _record(
        result_files=SimpleNamespace(state=SimpleNamespace(value="overwritten")),
        artifacts=SimpleNamespace(state=SimpleNamespace(value="current")),
    )

    job = PersistentJob.from_run_record(record)

    assert job.result_files_state == "overwritten"
    assert not job.result_files_verified


def test_legacy_artifacts_are_mapped_as_result_files():
    record = _record(
        artifacts=SimpleNamespace(state=SimpleNamespace(value="current")),
    )

    job = PersistentJob.from_run_record(record)

    assert job.result_files_state == "current"
    assert job.artifact_state == "current"  # compatibility alias


def test_explicit_result_file_check_marks_state_as_verified():
    stored = _record(
        artifacts=SimpleNamespace(state=SimpleNamespace(value="current")),
    )
    checked = _record(
        artifacts=SimpleNamespace(state=SimpleNamespace(value="overwritten")),
    )

    class Store:
        @staticmethod
        def runs():
            return (stored,)

    class Manager:
        store = Store()

        def __init__(self):
            self.checked = []

        def check_result_files(self, run_id):
            self.checked.append(run_id)
            return checked

    manager = Manager()
    source = PersistentJobSource(manager)

    listed = source.jobs()[0]
    verified = source.check_result_files(stored.id)

    assert listed.result_files_state == "current"
    assert not listed.result_files_verified
    assert verified.result_files_state == "overwritten"
    assert verified.result_files_verified
    assert manager.checked == [stored.id]


def test_result_file_check_supports_legacy_backend_name():
    record = _record(
        artifacts=SimpleNamespace(state=SimpleNamespace(value="current")),
    )

    class Store:
        @staticmethod
        def runs():
            return (record,)

    class Manager:
        store = Store()

        def check_artifacts(self, run_id):
            assert run_id == record.id
            return record

    source = PersistentJobSource(Manager())

    assert source.supports_result_file_check
    assert source.check_result_files(record.id).result_files_verified
