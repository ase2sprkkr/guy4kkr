"""Qt tests for the persistent calculation-job browser."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

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


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = True
    supports_results = True
    supports_attach = True
    supports_result_file_check = False

    def __init__(self, jobs):
        self._jobs = tuple(jobs)
        self.loaded = []
        self.refresh_calls = 0
        self.attach_calls = []
        self.attach_callbacks = {}
        self.runners = {}

    def jobs(self):
        return self._jobs

    def refresh(self):
        self.refresh_calls += 1
        return self._jobs

    def attach(self, job_id, *, callback=None, output_listener=None):
        self.attach_calls.append(job_id)
        self.attach_callbacks[job_id] = callback
        return self.runners.setdefault(job_id, object())

    def load_result(self, job_id):
        self.loaded.append(job_id)
        return type("Result", (), {"output_values": {}})()


def test_history_groups_jobs_and_shows_selected_metadata():
    _application = QApplication.instance() or QApplication([])
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

    assert dialog.windowTitle() == "Calculation Jobs"
    assert [dialog.group_by.itemText(i) for i in range(dialog.group_by.count())] == [
        "Started date",
        "Finished date",
        "Status",
        "Task",
        "Execution target",
    ]
    assert dialog.tree.headerItem().text(2) == "Started"
    assert dialog.tree.headerItem().text(3) == "Finished"
    assert dialog.tree.topLevelItem(0).text(0) == "2026-10-13"
    assert dialog.detail_title.text() == "Fe-SCF"
    assert dialog.status_value.text() == "Running"
    assert dialog.started_value.text() == "2026-10-13 10:00:00"
    assert dialog.finished_value.text() == "—"
    assert dialog.result_files_value.text() == "—"
    assert dialog.result_widget._history_button is None
    assert not dialog.monitor_button.isHidden()
    assert dialog.load_result_button.isHidden()

    dialog.group_by.setCurrentText("Finished date")
    assert dialog.tree.topLevelItem(0).text(0) == "Not finished"
    assert dialog.tree.topLevelItem(1).text(0) == "2026-10-12"

    dialog.group_by.setCurrentText("Task")
    assert dialog.tree.topLevelItem(0).text(0) == "SCF"
    dialog.close()


def test_finished_job_shows_stable_finished_time_and_can_load_result():
    _application = QApplication.instance() or QApplication([])
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

    assert dialog.finished_value.text() == "2026-10-13 10:37:00"
    assert dialog.tree.topLevelItem(0).child(0).text(3) == "2026-10-13 10:37:00"
    assert dialog.result_files_value.text() == "Current (stored, not checked)"
    assert dialog.monitor_button.isHidden()
    assert not dialog.load_result_button.isHidden()
    dialog._load_selected_result()

    assert source.loaded == [job.id]
    dialog.close()


def test_selected_final_job_verifies_result_files():
    _application = QApplication.instance() or QApplication([])
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
            return _job(
                job_id,
                state="finished",
                task="DOS",
                dataset="Fe-DOS",
                created_at="2026-10-13T08:00:00+00:00",
                finished_at="2026-10-13T08:37:00+00:00",
                result_files_state="overwritten",
                result_files_verified=True,
            )

    source = Source((job,))
    dialog = CalculationHistoryDialog(source=source)

    assert source.checked == [job.id]
    assert dialog.result_files_value.text() == "Overwritten"
    assert dialog._jobs_by_id[job.id].result_files_verified
    dialog.close()


def test_finishing_job_is_recovered_without_opening_monitor():
    application = QApplication.instance() or QApplication([])
    finishing = _job(
        "recovering-dos",
        state="finishing",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        attachable=True,
    )
    finished = _job(
        finishing.id,
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at=finishing.created_at,
        finished_at="2026-10-13T08:45:00+00:00",
        attachable=False,
    )
    source = _Source((finishing,))

    dialog = CalculationHistoryDialog(source=source)

    assert source.attach_calls == [finishing.id]
    assert dialog._recovery.active_ids == (finishing.id,)
    assert dialog.monitor_button.isHidden()

    source._jobs = (finished,)
    result = type("Result", (), {"output_values": {}})()
    source.attach_callbacks[finishing.id](result)
    application.processEvents()

    assert dialog._recovery.active_ids == ()
    assert dialog._jobs_by_id[finishing.id].state == "finished"
    assert not dialog.load_result_button.isHidden()
    dialog.close()


def test_nonattachable_active_job_does_not_offer_monitor():
    _application = QApplication.instance() or QApplication([])
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

    assert dialog.monitor_button.isHidden()
    dialog.close()


def test_empty_backend_shows_empty_state():
    _application = QApplication.instance() or QApplication([])
    dialog = CalculationHistoryDialog(source=_Source(()))

    assert not dialog.backend_notice.isHidden()
    assert dialog.backend_notice.text() == (
        "No persistent calculation jobs have been recorded yet."
    )
    assert dialog.tree.topLevelItemCount() == 0
    dialog.close()


def test_unavailable_backend_is_an_empty_nonfatal_history():
    _application = QApplication.instance() or QApplication([])

    class Source:
        available = False
        unavailable_reason = "Persistent jobs are not available yet."
        supports_refresh = False
        supports_results = False
        supports_attach = False
        supports_result_file_check = False

        @staticmethod
        def jobs():
            return ()

    dialog = CalculationHistoryDialog(source=Source())

    assert not dialog.backend_notice.isHidden()
    assert dialog.backend_notice.text() == "Persistent jobs are not available yet."
    assert not dialog.refresh_button.isEnabled()
    assert dialog.tree.topLevelItemCount() == 0
    dialog.close()
