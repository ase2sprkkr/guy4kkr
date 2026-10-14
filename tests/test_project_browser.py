"""Qt tests for the three-pane project browser."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTreeWidgetItem

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.projects import Project
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog

ROOT = "11111111111111111111111111111111"
CHILD = "22222222222222222222222222222222"


def _job(job_id: str, *, dataset: str) -> PersistentJob:
    return PersistentJob(
        id=job_id,
        state="finished",
        created_at="2026-10-13T08:00:00+00:00",
        updated_at="2026-10-13T08:45:00+00:00",
        finished_at="2026-10-13T08:45:00+00:00",
        task="DOS",
        directory=f"/tmp/{job_id}",
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


def _find_project_item(dialog: ProjectBrowserDialog, label: str) -> QTreeWidgetItem:
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


def test_project_browser_uses_parent_id_hierarchy_and_direct_run_membership():
    _application = QApplication.instance() or QApplication([])
    jobs = (
        _job("parent-run", dataset="Parent"),
        _job("child-run", dataset="Child"),
    )
    projects = (
        Project(
            id=ROOT,
            generation=1,
            name="Root",
            persistent_refs=("parent-run",),
        ),
        Project(
            id=CHILD,
            generation=1,
            name="Child project",
            parent_id=ROOT,
            persistent_refs=("child-run",),
        ),
    )
    dialog = ProjectBrowserDialog(
        repository=_ProjectSource(projects),
        job_source=_JobSource(jobs),
    )

    root = dialog.project_tree.topLevelItem(0)
    assert root.text(0) == "Root"
    assert root.child(0).text(0) == "Child project"
    assert [job.id for job in dialog.jobs.visible_jobs] == ["parent-run"]

    dialog.project_tree.setCurrentItem(root.child(0))
    assert [job.id for job in dialog.jobs.visible_jobs] == ["child-run"]
    assert dialog.jobs.detail_title.text() == "Child"
    dialog.close()


def test_unassigned_is_derived_from_runs_not_referenced_by_any_project():
    _application = QApplication.instance() or QApplication([])
    jobs = (
        _job("owned", dataset="Owned"),
        _job("free-1", dataset="Free one"),
        _job("free-2", dataset="Free two"),
    )
    dialog = ProjectBrowserDialog(
        repository=_ProjectSource(
            (
                Project(
                    id=ROOT,
                    generation=1,
                    name="Project",
                    persistent_refs=("owned",),
                ),
            )
        ),
        job_source=_JobSource(jobs),
    )

    unassigned = _find_project_item(dialog, "Unassigned")
    assert unassigned.text(1) == "2"
    dialog.project_tree.setCurrentItem(unassigned)
    assert {job.id for job in dialog.jobs.visible_jobs} == {"free-1", "free-2"}
    dialog.close()


def test_missing_persistent_reference_remains_visible_as_project_metadata():
    _application = QApplication.instance() or QApplication([])
    dialog = ProjectBrowserDialog(
        repository=_ProjectSource(
            (
                Project(
                    id=ROOT,
                    generation=1,
                    name="Project",
                    persistent_refs=("available", "missing"),
                ),
            )
        ),
        job_source=_JobSource((_job("available", dataset="Available"),)),
    )

    project = _find_project_item(dialog, "Project")
    assert project.text(1) == "1/2"
    assert not dialog.project_notice.isHidden()
    assert "1 persistent run reference" in dialog.project_notice.text()
    assert [job.id for job in dialog.jobs.visible_jobs] == ["available"]
    dialog.close()
