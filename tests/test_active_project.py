"""Tests for active-project ownership of newly created persistent runs."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.projects import ProjectRepository
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.main import GuiApplication


class _JobSource:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_result_file_check = False

    def __init__(self):
        self.changed = []
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    @staticmethod
    def jobs():
        return ()

    @staticmethod
    def job(_job_id):
        return None

    def job_changed(self, job_id):
        self.changed.append(job_id)
        return SimpleNamespace(id=str(job_id))

    @staticmethod
    def refresh():
        return ()


def test_active_project_is_explicit_not_current_browser_selection(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First")
    second = repository.create("Second")
    source = _JobSource()
    dialog = ProjectBrowserDialog(repository, source)
    requested = []
    dialog.activeProjectRequested.connect(requested.append)

    dialog.set_active_project(first.id)
    assert dialog.active_project_id == first.id
    assert dialog.active_project_label.text() == "Active project: First"

    # Browsing another project does not silently change calculation ownership.
    second_item = dialog.project_tree.topLevelItem(1)
    assert second_item.text(0) == "Second"
    dialog.project_tree.setCurrentItem(second_item)
    assert dialog.active_project_id == first.id
    assert requested == []

    dialog.set_active_project_button.click()
    assert requested == [second.id]
    dialog.close()


def test_live_job_change_is_idempotently_assigned_to_active_project(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Calculations")
    source = _JobSource()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=source,
        project_repository=repository,
    )
    gui.set_active_project(project.id)

    gui._persistent_job_changed("run-17")
    assigned = repository.project(project.id)

    assert source.changed == ["run-17"]
    assert assigned.persistent_refs == ("run-17",)
    assert assigned.generation == project.generation + 1

    gui._persistent_job_changed("run-17")
    unchanged = repository.project(project.id)

    assert source.changed == ["run-17", "run-17"]
    assert unchanged == assigned
