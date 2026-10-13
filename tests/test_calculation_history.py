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
    target: str = "SSH · cluster",
) -> PersistentJob:
    return PersistentJob(
        id=job_id,
        state=state,
        created_at=created_at,
        updated_at=created_at,
        task=task,
        directory=f"/tmp/{job_id}",
        dataset=dataset,
        target=target,
        return_code=0 if state == "finished" else None,
        message=None,
        artifact_state="current" if state == "finished" else None,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = True
    supports_results = True

    def __init__(self, jobs):
        self._jobs = tuple(jobs)
        self.loaded = []
        self.refresh_calls = 0

    def jobs(self):
        return self._jobs

    def refresh(self):
        self.refresh_calls += 1
        return self._jobs

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
            ),
        )
    )

    dialog = CalculationHistoryDialog(source=source)

    assert dialog.windowTitle() == "Calculation Jobs"
    assert [dialog.group_by.itemText(i) for i in range(dialog.group_by.count())] == [
        "Started date",
        "Status",
        "Task",
        "Execution target",
    ]
    assert dialog.tree.headerItem().text(2) == "Started"
    assert dialog.tree.topLevelItem(0).text(0) == "2026-10-13"
    assert dialog.detail_title.text() == "Fe-SCF"
    assert dialog.status_value.text() == "Running"
    assert dialog.started_value.text() == "2026-10-13 10:00:00"
    assert dialog.result_widget._history_button is None
    assert dialog.load_result_button.isHidden()

    dialog.group_by.setCurrentText("Task")
    assert dialog.tree.topLevelItem(0).text(0) == "SCF"
    dialog.close()


def test_finished_job_can_load_historical_result():
    _application = QApplication.instance() or QApplication([])
    job = _job(
        "finished-dos",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
    )
    source = _Source((job,))
    dialog = CalculationHistoryDialog(source=source)

    assert not dialog.load_result_button.isHidden()
    dialog._load_selected_result()

    assert source.loaded == [job.id]
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

        @staticmethod
        def jobs():
            return ()

    dialog = CalculationHistoryDialog(source=Source())

    assert not dialog.backend_notice.isHidden()
    assert dialog.backend_notice.text() == "Persistent jobs are not available yet."
    assert not dialog.refresh_button.isEnabled()
    assert dialog.tree.topLevelItemCount() == 0
    dialog.close()
