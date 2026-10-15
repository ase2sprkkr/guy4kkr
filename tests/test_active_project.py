"""Tests for active-project ownership of newly created persistent runs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from ase import Atoms
from ase2sprkkr.execution import ProjectRepository, ProjectRepositoryError

from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.main import GuiApplication


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


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
        self.changed.append(str(job_id))
        return self._jobs.get(str(job_id))

    @staticmethod
    def refresh():
        return ()


class _LaunchWindow(QWidget):
    persistentJobChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.execution_manager = None

    def set_execution_context(self, manager):
        self.execution_manager = manager


def _configured_gui(tmp_path, repository):
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=_JobSource(),
        project_repository=repository,
    )
    gui.controller.replace_structure(Atoms("Fe"))
    gui.controller.replace_input_parameters(_Parameters())
    gui.controller.change_directory(str(tmp_path))
    return gui


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


def test_launch_request_captures_active_project_before_later_selection_change(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    launch_project = repository.create("Launch")
    later_project = repository.create("Later")
    gui = _configured_gui(tmp_path, repository)
    gui.set_active_project(launch_project.id)

    request = gui.controller.create_calculation_request()
    gui.set_active_project(later_project.id)

    assert request.project_id == launch_project.id
    assert gui.active_project_id == later_project.id

    monitor_window = _LaunchWindow()
    gui._track_launch_monitor(monitor_window)
    assert monitor_window.execution_manager is gui.execution_manager
    assert gui.execution_manager.projects is repository
    monitor_window.close()


def test_execution_uses_launch_project_after_active_selection_changes(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    launch_project = repository.create("Launch")
    later_project = repository.create("Later")
    gui = _configured_gui(tmp_path, repository)
    gui.set_active_project(launch_project.id)

    request = gui.controller.create_calculation_request()
    gui.set_active_project(later_project.id)

    execution = SprkkrExecution(
        request,
        object(),
        execution_manager=gui.execution_manager,
    )
    bound_manager = execution._persistent_context()

    assert bound_manager.project_id == launch_project.id
    assert bound_manager.projects is repository
    assert gui.active_project_id == later_project.id


def test_repository_error_does_not_clear_active_project(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    active = repository.create("Active")
    target = repository.create("Target")
    gui = _configured_gui(tmp_path, repository)
    gui.set_active_project(active.id)

    def fail(_project_id):
        raise ProjectRepositoryError("temporary repository failure")

    monkeypatch.setattr(repository, "project", fail)

    with pytest.raises(ProjectRepositoryError, match="temporary repository failure"):
        gui.set_active_project(target.id)

    assert gui.active_project_id == active.id
