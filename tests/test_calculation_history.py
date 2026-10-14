"""Qt tests for the persistent calculation-job browser."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog


def _job(
    job_id: str,
    *,
    state: str,
    task: str,
    dataset: str,
    created_at: str,
    finished_at: str | None = None,
    target: str = "SSH · cluster",
    attachable: bool | None = None,
    result_files_state: str | None = None,
    result_files_verified: bool = False,
) -> PersistentJob:
    if attachable is None:
        attachable = state not in {"finished", "failed", "cancelled"}
    if result_files_state is None and state == "finished":
        result_files_state = "current"
    return PersistentJob(
        id=job_id,
        state=state,
        created_at=created_at,
        updated_at=created_at,
        finished_at=finished_at,
        task=task,
        directory=f"/tmp/{job_id}",
        dataset=dataset,
        target=target,
        return_code=0 if state == "finished" else None,
        message=None,
        result_files_state=result_files_state,
        attachable=attachable,
        result_files_verified=result_files_verified,
    )


class _Source(QObject):
    changed = pyqtSignal(str)
    reloaded = pyqtSignal()

    available = True
    unavailable_reason = None
    recovery_error = None
    supports_refresh = True
    supports_results = True
    supports_attach = True
    supports_result_file_check = False

    def __init__(self, jobs):
        super().__init__()
        self._jobs = tuple(jobs)
        self.loaded = []
        self.refresh_calls = 0
        self.attach_calls = []
        self.attach_callbacks = {}
        self.runners = {}
        self.recovering = set()

    def jobs(self):
        return self._jobs

    def job(self, job_id):
        return next((job for job in self._jobs if job.id == job_id), None)

    def is_recovering(self, job_id):
        return job_id in self.recovering

    def refresh(self):
        self.refresh_calls += 1
        self.reloaded.emit()
        return self._jobs

    def job_changed(self, job_id):
        self.changed.emit(job_id)
        return self.job(job_id)

    def attach(self, job_id, *, callback=None, output_listener=None):
        self.attach_calls.append(job_id)
        self.attach_callbacks[job_id] = callback
        return self.runners.setdefault(job_id, object())

    def load_result(self, job_id):
        self.loaded.append(job_id)
        return SimpleNamespace(output_values={})


def _jobs(dialog):
    return dialog.jobs


def test_history_groups_jobs_and_shows_selected_metadata():
    source = _Source(
        (
            _job(
                "newer-running",
                state="running",
                task="SCF",
                dataset="Fe-SCF",
                created_at="2026-10-13T08:00:00+00:00",
            ),
            _job(
                "older-dos",
                state="finished",
                task="DOS",
                dataset="Fe-DOS",
                created_at="2026-10-12T08:00:00+00:00",
                finished_at="2026-10-12T08:45:00+00:00",
            ),
        )
    )

    dialog = CalculationHistoryDialog(source=source)
    jobs = _jobs(dialog)

    assert dialog.windowTitle() == "Calculation Jobs"
    assert [jobs.group_by.itemText(i) for i in range(jobs.group_by.count())] == [
        "Started date",
        "Finished date",
        "Status",
        "Task",
        "Execution target",
    ]
    assert jobs.tree.headerItem().text(2) == "Started"
    assert jobs.tree.headerItem().text(3) == "Finished"
    assert jobs.tree.topLevelItem(0).text(0) == "2026-10-13"
    assert jobs.detail_title.text() == "Fe-SCF"
    assert jobs.status_value.text() == "Running"
    assert jobs.started_value.text() == "2026-10-13 10:00:00"
    assert jobs.finished_value.text() == "—"
    assert jobs.result_files_value.text() == "—"
    assert jobs.result_widget._history_button is None
    assert not jobs.monitor_button.isHidden()
    assert jobs.load_result_button.isHidden()

    jobs.group_by.setCurrentText("Finished date")
    assert jobs.tree.topLevelItem(0).text(0) == "Not finished"
    assert jobs.tree.topLevelItem(1).text(0) == "2026-10-12"

    jobs.group_by.setCurrentText("Task")
    assert jobs.tree.topLevelItem(0).text(0) == "SCF"
    dialog.close()


def test_finished_job_shows_stable_finished_time_and_can_load_result():
    job = _job(
        "finished-dos",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        finished_at="2026-10-13T08:37:00+00:00",
    )
    source = _Source((job,))
    dialog = CalculationHistoryDialog(source=source)
    jobs = _jobs(dialog)

    assert jobs.finished_value.text() == "2026-10-13 10:37:00"
    assert jobs.tree.topLevelItem(0).child(0).text(3) == "2026-10-13 10:37:00"
    assert jobs.result_files_value.text() == "Current (stored, not checked)"
    assert jobs.monitor_button.isHidden()
    assert not jobs.load_result_button.isHidden()
    jobs._load_selected_result()

    assert source.loaded == [job.id]
    dialog.close()


def test_selected_final_job_verifies_result_files():
    job = _job(
        "finished-overwritten",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        finished_at="2026-10-13T08:37:00+00:00",
    )

    class Source(_Source):
        supports_result_file_check = True

        def __init__(self, jobs):
            super().__init__(jobs)
            self.checked = []

        def check_result_files(self, job_id):
            self.checked.append(job_id)
            checked = _job(
                job_id,
                state="finished",
                task="DOS",
                dataset="Fe-DOS",
                created_at="2026-10-13T08:00:00+00:00",
                finished_at="2026-10-13T08:37:00+00:00",
                result_files_state="overwritten",
                result_files_verified=True,
            )
            self._jobs = (checked,)
            self.changed.emit(job_id)
            return checked

    source = Source((job,))
    dialog = CalculationHistoryDialog(source=source)
    jobs = _jobs(dialog)

    assert source.checked == [job.id]
    assert jobs.result_files_value.text() == "Overwritten"
    assert jobs._jobs_by_id[job.id].result_files_verified
    dialog.close()


def test_recovering_job_does_not_offer_second_monitor():
    job = _job(
        "recovering-dos",
        state="finishing",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        attachable=True,
    )
    source = _Source((job,))
    source.recovering.add(job.id)

    dialog = CalculationHistoryDialog(source=source)

    assert dialog.jobs.monitor_button.isHidden()
    dialog.close()


def test_nonattachable_active_job_does_not_offer_monitor():
    source = _Source(
        (
            _job(
                "legacy-local",
                state="running",
                task="SCF",
                dataset="Fe-SCF",
                created_at="2026-10-13T08:00:00+00:00",
                attachable=False,
            ),
        )
    )
    dialog = CalculationHistoryDialog(source=source)

    assert dialog.jobs.monitor_button.isHidden()
    dialog.close()


def test_source_change_rebuilds_visible_history():
    source = _Source(
        (
            _job(
                "running",
                state="running",
                task="SCF",
                dataset="Fe",
                created_at="2026-10-13T08:00:00+00:00",
            ),
        )
    )
    dialog = CalculationHistoryDialog(source=source)

    source._jobs = (
        _job(
            "running",
            state="finished",
            task="SCF",
            dataset="Fe",
            created_at="2026-10-13T08:00:00+00:00",
            finished_at="2026-10-13T08:30:00+00:00",
        ),
    )
    source.changed.emit("running")

    assert dialog.jobs.status_value.text() == "Finished"
    assert not dialog.jobs.load_result_button.isHidden()
    dialog.close()


def test_empty_backend_shows_empty_state():
    dialog = CalculationHistoryDialog(source=_Source(()))

    assert not dialog.jobs.backend_notice.isHidden()
    assert dialog.jobs.backend_notice.text() == (
        "No persistent calculation jobs have been recorded yet."
    )
    assert dialog.jobs.tree.topLevelItemCount() == 0
    dialog.close()


def test_unavailable_backend_is_an_empty_nonfatal_history():
    source = _Source(())
    source.available = False
    source.unavailable_reason = "Persistent jobs are not available yet."
    source.supports_refresh = False

    dialog = CalculationHistoryDialog(source=source)

    assert not dialog.jobs.backend_notice.isHidden()
    assert dialog.jobs.backend_notice.text() == "Persistent jobs are not available yet."
    assert not dialog.jobs.refresh_button.isEnabled()
    assert dialog.jobs.tree.topLevelItemCount() == 0
    dialog.close()
