"""Qt tests for the three-pane project browser."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QTreeWidgetItem

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.projects import Project
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog

ROOT = "11111111111111111111111111111111"
CHILD = "22222222222222222222222222222222"


def _job(job_id: str, *, dataset: str) -> PersistentJob:
    return PersistentJob(id=job_id, state="finished", created_at="2026-10-13T08:00:00+00:00", updated_at="2026-10-13T08:45:00+00:00", finished_at="2026-10-13T08:45:00+00:00", task="DOS", directory=f"/tmp/{job_id}", dataset=dataset, target="Local", return_code=0, message=None, result_files_state="current")


class _JobSource(QObject):
    changed = pyqtSignal(str)
    reloaded = pyqtSignal()
    available = True
    unavailable_reason = None
    recovery_error = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_result_file_check = False
    def __init__(self, jobs):
        super().__init__(); self._jobs = tuple(jobs)
    def jobs(self): return self._jobs
    def is_recovering(self, _job_id): return False


class _ProjectSource(QObject):
    changed = pyqtSignal(str)
    reloaded = pyqtSignal()
    def __init__(self, projects):
        super().__init__(); self._projects = tuple(projects)
    def projects(self): return self._projects
    def refresh(self): self.reloaded.emit(); return self._projects


def _find(dialog: ProjectBrowserDialog, label: str) -> QTreeWidgetItem:
    pending = [dialog.project_tree.topLevelItem(i) for i in range(dialog.project_tree.topLevelItemCount())]
    while pending:
        item = pending.pop(0)
        if item.text(0) == label: return item
        pending.extend(item.child(i) for i in range(item.childCount()))
    raise AssertionError(label)


def test_project_browser_uses_parent_id_hierarchy_and_direct_membership():
    projects = (
        Project(id=ROOT, generation=1, name="Root", persistent_refs=("parent-run",)),
        Project(id=CHILD, generation=1, name="Child project", parent_id=ROOT, persistent_refs=("child-run",)),
    )
    dialog = ProjectBrowserDialog(_ProjectSource(projects), _JobSource((_job("parent-run", dataset="Parent"), _job("child-run", dataset="Child"))))
    root = dialog.project_tree.topLevelItem(0)
    assert root.text(0) == "Root"
    assert root.child(0).text(0) == "Child project"
    assert [job.id for job in dialog.jobs.visible_jobs] == ["parent-run"]
    dialog.project_tree.setCurrentItem(root.child(0))
    assert [job.id for job in dialog.jobs.visible_jobs] == ["child-run"]
    dialog.close()


def test_unassigned_is_derived_from_unreferenced_runs():
    dialog = ProjectBrowserDialog(_ProjectSource((Project(id=ROOT, generation=1, name="Project", persistent_refs=("owned",)),)), _JobSource((_job("owned", dataset="Owned"), _job("free", dataset="Free"))))
    unassigned = _find(dialog, "Unassigned")
    assert unassigned.text(1) == "1"
    dialog.project_tree.setCurrentItem(unassigned)
    assert [job.id for job in dialog.jobs.visible_jobs] == ["free"]
    dialog.close()


def test_job_reload_recomputes_project_counts_and_unassigned():
    project_source = _ProjectSource((Project(id=ROOT, generation=1, name="Project", persistent_refs=("owned", "late")),))
    job_source = _JobSource((_job("owned", dataset="Owned"),))
    dialog = ProjectBrowserDialog(project_source, job_source)
    assert _find(dialog, "Project").text(1) == "1/2"
    job_source._jobs = (_job("owned", dataset="Owned"), _job("late", dataset="Late"), _job("free", dataset="Free"))
    job_source.reloaded.emit()
    assert _find(dialog, "Project").text(1) == "2"
    assert _find(dialog, "Unassigned").text(1) == "1"
    dialog.close()


def test_project_reload_updates_tree():
    source = _ProjectSource((Project(id=ROOT, generation=1, name="Before"),))
    dialog = ProjectBrowserDialog(source, _JobSource(()))
    source._projects = (Project(id=ROOT, generation=2, name="After"),)
    source.reloaded.emit()
    assert _find(dialog, "After").text(0) == "After"
    dialog.close()
