"""Tests for active-project ownership of newly created persistent runs."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from ase2sprkkr.execution import ProjectRepository

from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
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
        self._jobs = {}

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def jobs(self):
        return tuple(self._jobs.values())

    def job(self, job_id):
        return self._jobs.get(str(job_id))

    def job_changed(self, job_id):
        job_id = str(job_id)
        self.changed.append(job_id)
        job = self._jobs.setdefault(job_id, SimpleNamespace(id=job_id))
        for listener in tuple(self._listeners):
            listener(job_id)
        return job

    @staticmethod
    def refresh():
        return ()


class _LaunchWindow(QWidget):
    persistentJobChanged = pyqtSignal(str)


def test_active_project_is_explicit_not_current_browser_selection(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First")
    second = repository.create("Second")
    source = _JobSource()
    dialog = ProjectBrowserDialog(repository, PersistentJobsController(source))
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


def test_launch_is_assigned_to_project_active_when_monitor_is_tracked(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    launch_project = repository.create("Launch")
    later_project = repository.create("Later")
    source = _JobSource()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=source,
        project_repository=repository,
    )
    gui.set_active_project(launch_project.id)
    monitor_window = _LaunchWindow()
    gui._track_launch_monitor(monitor_window)

    # Persistent-id delivery can be delayed by the backend/store. A later user
    # project selection must not rewrite the launch provenance of this run.
    gui.set_active_project(later_project.id)
    monitor_window.persistentJobChanged.emit("run-17")

    assigned = repository.project(launch_project.id)
    later = repository.project(later_project.id)
    assert source.changed == ["run-17"]
    assert assigned.persistent_refs == ("run-17",)
    assert later.persistent_refs == ()
    assert assigned.generation == launch_project.generation + 1
    assert gui.persistent_jobs_controller._monitor_windows == {
        "run-17": monitor_window
    }

    # A later lifecycle report reloads metadata but does not assign again.
    monitor_window.persistentJobChanged.emit("run-17")
    unchanged = repository.project(launch_project.id)

    assert source.changed == ["run-17", "run-17"]
    assert unchanged == assigned
    monitor_window.close()
