"""Qt tests for the three-pane persistent project browser."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog


def _job(job_id: str, *, dataset: str, directory: str) -> PersistentJob:
    return PersistentJob(
        id=job_id,
        state="finished",
        created_at="2026-10-13T08:00:00+00:00",
        updated_at="2026-10-13T08:45:00+00:00",
        finished_at="2026-10-13T08:45:00+00:00",
        task="DOS",
        directory=directory,
        dataset=dataset,
        target="Local",
        return_code=0,
        message=None,
        result_files_state="current",
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_result_file_check = False

    def __init__(self, jobs):
        self._jobs = tuple(jobs)

    def jobs(self):
        return self._jobs


def _select_project(dialog: ProjectBrowserDialog, label: str) -> None:
    for index in range(dialog.project_tree.topLevelItemCount()):
        item = dialog.project_tree.topLevelItem(index)
        if item.text(0) == label:
            dialog.project_tree.setCurrentItem(item)
            return
    raise AssertionError(f"Project {label!r} not found")


def test_project_browser_filters_middle_job_tree_by_project():
    _application = QApplication.instance() or QApplication([])
    jobs = (
        _job("a-1", dataset="A one", directory="/tmp/a1"),
        _job("b-1", dataset="B one", directory="/tmp/b1"),
        _job("a-2", dataset="A two", directory="/tmp/a2"),
    )
    project_ids = {"a-1": "project-a", "a-2": "project-a", "b-1": "project-b"}

    dialog = ProjectBrowserDialog(
        source=_Source(jobs),
        project_id_for=lambda job: project_ids[job.id],
    )

    assert dialog.windowTitle() == "Project Browser"
    assert dialog.project_tree.topLevelItemCount() == 2
    assert dialog.project_tree.topLevelItem(0).text(0) == "project-a"
    assert dialog.project_tree.topLevelItem(0).text(1) == "2"

    _select_project(dialog, "project-b")
    assert len(dialog._jobs) == 1
    assert dialog._jobs[0].id == "b-1"
    assert dialog.detail_title.text() == "B one"
    dialog.close()


def test_unassigned_jobs_are_not_grouped_by_working_directory():
    _application = QApplication.instance() or QApplication([])
    dialog = ProjectBrowserDialog(
        source=_Source(
            (
                _job("one", dataset="One", directory="/tmp/first"),
                _job("two", dataset="Two", directory="/different/place"),
            )
        )
    )

    assert dialog.project_tree.topLevelItemCount() == 1
    item = dialog.project_tree.topLevelItem(0)
    assert item.text(0) == "Unassigned"
    assert item.text(1) == "2"
    assert len(dialog._jobs) == 2
    dialog.close()
