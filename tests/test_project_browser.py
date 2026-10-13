"""Qt tests for the three-pane persistent project browser."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTreeWidgetItem

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.projects import ProjectRecord
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


class _JobSource:
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


class _ProjectSource:
    def __init__(self, projects):
        self._projects = tuple(projects)

    def projects(self):
        return self._projects


def _find_project_item(
    dialog: ProjectBrowserDialog,
    label: str,
) -> QTreeWidgetItem:
    pending = [
        dialog.project_tree.topLevelItem(index)
        for index in range(dialog.project_tree.topLevelItemCount())
    ]
    while pending:
        item = pending.pop(0)
        if item.text(0) == label:
            return item
        pending.extend(item.child(index) for index in range(item.childCount()))
    raise AssertionError(f"Project {label!r} not found")


def test_project_browser_filters_jobs_from_project_owned_ids():
    _application = QApplication.instance() or QApplication([])
    jobs = (
        _job("a-1", dataset="A one", directory="/tmp/a1"),
        _job("b-1", dataset="B one", directory="/tmp/b1"),
        _job("a-2", dataset="A two", directory="/tmp/a2"),
    )
    projects = (
        ProjectRecord(
            id="root",
            name="Project A",
            job_ids=("a-1", "a-2"),
            child_project_ids=("child",),
        ),
        ProjectRecord(id="child", name="Project B", job_ids=("b-1",)),
    )

    dialog = ProjectBrowserDialog(
        source=_JobSource(jobs),
        project_source=_ProjectSource(projects),
    )

    assert dialog.windowTitle() == "Project Browser"
    assert dialog.project_tree.topLevelItemCount() == 1
    root = dialog.project_tree.topLevelItem(0)
    assert root.text(0) == "Project A"
    assert root.text(1) == "2"
    assert root.child(0).text(0) == "Project B"

    dialog.project_tree.setCurrentItem(root.child(0))
    assert [job.id for job in dialog._jobs] == ["b-1"]
    assert dialog.detail_title.text() == "B one"
    dialog.close()


def test_parent_project_does_not_implicitly_include_child_jobs():
    _application = QApplication.instance() or QApplication([])
    dialog = ProjectBrowserDialog(
        source=_JobSource(
            (
                _job("parent-job", dataset="Parent", directory="/tmp/parent"),
                _job("child-job", dataset="Child", directory="/tmp/child"),
            )
        ),
        project_source=_ProjectSource(
            (
                ProjectRecord(
                    id="parent",
                    name="Parent project",
                    job_ids=("parent-job",),
                    child_project_ids=("child",),
                ),
                ProjectRecord(
                    id="child",
                    name="Child project",
                    job_ids=("child-job",),
                ),
            )
        ),
    )

    dialog.project_tree.setCurrentItem(_find_project_item(dialog, "Parent project"))
    assert [job.id for job in dialog._jobs] == ["parent-job"]
    dialog.close()


def test_unassigned_view_contains_only_jobs_not_owned_by_any_project():
    _application = QApplication.instance() or QApplication([])
    dialog = ProjectBrowserDialog(
        source=_JobSource(
            (
                _job("owned", dataset="Owned", directory="/tmp/first"),
                _job("free-1", dataset="Free one", directory="/tmp/second"),
                _job("free-2", dataset="Free two", directory="/different/place"),
            )
        ),
        project_source=_ProjectSource(
            (ProjectRecord(id="p", name="Project", job_ids=("owned",)),)
        ),
    )

    unassigned = _find_project_item(dialog, "Unassigned")
    assert unassigned.text(1) == "2"
    dialog.project_tree.setCurrentItem(unassigned)
    assert {job.id for job in dialog._jobs} == {"free-1", "free-2"}
    dialog.close()
