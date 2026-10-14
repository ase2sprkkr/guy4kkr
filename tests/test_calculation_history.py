"""Qt tests for reusable persistent calculation-job browsing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog


def _job(job_id, *, state="finished", dataset="Job", attachable=False):
    return PersistentJob(
        id=job_id,
        state=state,
        created_at="2026-10-13T08:00:00+00:00",
        updated_at="2026-10-13T08:45:00+00:00",
        finished_at=(
            "2026-10-13T08:45:00+00:00" if state == "finished" else None
        ),
        task="DOS",
        directory=f"/tmp/{job_id}",
        dataset=dataset,
        target="Local",
        return_code=0 if state == "finished" else None,
        message=None,
        result_files_state="current" if state == "finished" else None,
        attachable=attachable,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = True
    supports_attach = True
    supports_result_file_check = False

    def __init__(self, jobs):
        self._jobs = tuple(jobs)
        self.attach_calls = []
        self.attach_callbacks = {}
        self.loaded = []

    def jobs(self):
        return self._jobs

    def attach(self, job_id, *, callback=None, output_listener=None):
        self.attach_calls.append(job_id)
        self.attach_callbacks[job_id] = callback
        return object()

    def load_result(self, job_id):
        self.loaded.append(job_id)
        return type("Result", (), {"output_values": {}})()


def test_dialog_composes_reusable_jobs_widget():
    _application = QApplication.instance() or QApplication([])
    dialog = CalculationHistoryDialog(source=_Source((_job("run", dataset="Fe"),)))

    assert dialog.windowTitle() == "Calculation Jobs"
    assert dialog.jobs.detail_title.text() == "Fe"
    assert dialog.jobs.tree.topLevelItemCount() == 1
    assert dialog.jobs.result_widget._history_button is None
    dialog.close()


def test_visible_filter_is_presentation_only_and_does_not_limit_recovery():
    _application = QApplication.instance() or QApplication([])
    finishing = _job(
        "finishing",
        state="finishing",
        dataset="Finishing",
        attachable=True,
    )
    visible = _job("visible", dataset="Visible")
    source = _Source((finishing, visible))
    dialog = CalculationHistoryDialog(source=source)

    dialog.jobs.set_visible_refs((visible.id,))

    assert [job.id for job in dialog.jobs.visible_jobs] == [visible.id]
    assert source.attach_calls == [finishing.id]
    assert dialog.jobs._recovery.active_ids == (finishing.id,)
    dialog.close()


def test_finished_job_can_load_result():
    _application = QApplication.instance() or QApplication([])
    source = _Source((_job("finished", dataset="DOS"),))
    dialog = CalculationHistoryDialog(source=source)

    assert not dialog.jobs.load_result_button.isHidden()
    dialog.jobs._load_selected_result()
    assert source.loaded == ["finished"]
    dialog.close()


def test_empty_history_has_nonfatal_empty_state():
    _application = QApplication.instance() or QApplication([])
    source = _Source(())
    dialog = CalculationHistoryDialog(source=source)

    assert not dialog.jobs.backend_notice.isHidden()
    assert "No persistent calculation jobs" in dialog.jobs.backend_notice.text()
    assert dialog.jobs.tree.topLevelItemCount() == 0
    dialog.close()
