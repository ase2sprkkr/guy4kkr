"""Project selection in execution setup is per run, not a workspace mutation."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication
from kkrunner.projects import ProjectRepository

from guy4ase.gui.dialogs import profiles as profiles_module
from guy4ase.gui.dialogs import project_edit as project_edit_module
from guy4ase.gui.dialogs.project_edit import ProjectEditDialog
from guy4ase.gui.dialogs.profiles import ProfileSelectionDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_execution_dialog_lists_projects_and_preselects_active(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Materials")
    nested = repository.create("Fe calculations", parent_id=parent.id)
    other = repository.create("Other")

    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=nested.id,
        directory=str(tmp_path),
    )
    assert dialog.project_id() == nested.id
    assert dialog.project_selector.currentText() == "Materials / Fe calculations"
    assert dialog.project_selector.count() == 4  # Unassigned + 3 projects

    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(other.id)
    )
    assert dialog.project_id() == other.id
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_execution_dialog_can_explicitly_select_unassigned(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    active = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=str(tmp_path),
    )
    assert dialog.project_id() == active.id
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.project_id() is None
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_unknown_active_project_falls_back_to_unassigned(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    repository.create("Available")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id="deleted-project",
        directory=str(tmp_path),
    )
    assert dialog.project_id() is None
    dialog.close()


def test_create_project_in_execution_dialog_is_selected_and_persisted(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    monkeypatch.setattr(
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("New calculation") or self.DialogCode.Accepted),
    )
    dialog.new_project_button.click()

    created_id = dialog.project_id()
    assert created_id is not None
    assert repository.project(created_id).name == "New calculation"
    assert repository.project(created_id).parent_id is None
    assert dialog.project_selector.currentText() == "New calculation"
    assert dialog.project_selector.count() == 2
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()

    # The project is durable; it can be chosen in a later launch.
    again = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    assert again.project_selector.findData(created_id) >= 0
    again.close()


def test_create_subproject_under_current_selection(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Materials")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=parent.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("Fe") or self.DialogCode.Accepted),
    )
    dialog.new_project_button.click()

    child_id = dialog.project_id()
    assert child_id is not None and child_id != parent.id
    assert repository.project(child_id).parent_id == parent.id
    assert dialog.project_selector.currentText() == "Materials / Fe"
    assert dialog.project_selector.count() == 3
    dialog.close()


def test_cancel_create_project_preserves_selection(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=current.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(ProjectEditDialog, "exec", lambda self: self.DialogCode.Rejected)
    dialog.new_project_button.click()

    assert dialog.project_id() == current.id
    assert dialog.project_selector.count() == 2
    assert [project.name for project in repository.projects()] == ["Current"]
    dialog.close()


def test_project_creation_error_does_not_close_execution_dialog(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=current.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("Invalid") or self.DialogCode.Accepted),
    )

    def fail_create(name, *, parent_id=None, directory=None):
        assert name == "Invalid"
        assert parent_id == current.id
        raise ValueError("Invalid project name")

    monkeypatch.setattr(repository, "create", fail_create)
    warnings = []
    monkeypatch.setattr(
        profiles_module.QMessageBox, "warning",
        lambda _dialog, title, message: warnings.append((title, message)),
    )
    dialog.new_project_button.click()

    assert warnings == [("Create Project Failed", "Invalid project name")]
    assert dialog.project_id() == current.id
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.close()


def test_project_directory_switch_and_manual_override(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    first_directory = tmp_path / "project_work"
    second_directory = tmp_path / "other_work"
    first = repository.create("First", directory=first_directory)
    second = repository.create("Second", directory=second_directory)
    no_directory = repository.create("No directory")
    initial = str(tmp_path / "workspace")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=initial
    )
    assert dialog.directory_name() == initial

    # Before any explicit selection, the project's directory follows its choice.
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(first.id))
    assert dialog.directory_name() == str(first_directory)
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == str(second_directory)
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(no_directory.id)
    )
    assert dialog.directory_name() == initial
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == initial

    # An explicit directory is a per-run override, even after switching projects.
    manual = str(tmp_path / "manual")
    dialog.directory_edit.setText(manual)
    dialog._directory_edited(manual)
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(first.id))
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(no_directory.id)
    )
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == manual
    dialog.close()


def test_active_project_directory_is_default_on_dialog_open(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project_directory = tmp_path / "project"
    active = repository.create("Active", directory=project_directory)
    workspace_directory = tmp_path / "workspace"
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=str(workspace_directory),
    )
    assert dialog.project_id() == active.id
    assert dialog.directory_name() == str(project_directory)
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == str(workspace_directory)
    dialog.close()

    # No inherited workspace directory is required for a project default.
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=None,
    )
    assert dialog.directory_name() == str(project_directory)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_browsed_directory_is_explicit_even_after_project_change(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First", directory=tmp_path / "first")
    second = repository.create("Second", directory=tmp_path / "second")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=first.id,
    )
    assert dialog.directory_name() == str(tmp_path / "first")

    chosen = str(tmp_path / "chosen")
    monkeypatch.setattr(
        profiles_module.QFileDialog, "getExistingDirectory",
        lambda *_args: chosen,
    )
    dialog._browse_directory()
    assert dialog.directory_name() == chosen
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == chosen
    dialog.close()


def test_typing_directory_after_project_selection_overrides_project(
    application, tmp_path
):
    from PyQt6.QtTest import QTest

    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First", directory=tmp_path / "first")
    second = repository.create("Second", directory=tmp_path / "second")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=first.id
    )
    assert dialog.directory_name() == str(tmp_path / "first")

    dialog.directory_edit.clear()
    QTest.keyClicks(dialog.directory_edit, str(tmp_path / "manual"))
    assert dialog.directory_name() == str(tmp_path / "manual")
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == str(tmp_path / "manual")
    dialog.close()


def test_new_project_dialog_sets_working_directory(application, monkeypatch, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    directory = tmp_path / "new-project"
    dialog = ProfileSelectionDialog(project_repository=repository, directory=str(tmp_path))

    def create(project_dialog):
        project_dialog.name_edit.setText("New")
        project_dialog.directory_edit.setText(str(directory))
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", create)
    dialog.new_project_button.click()
    project_id = dialog.project_id()
    assert project_id is not None
    assert repository.project(project_id).directory == str(directory)
    assert dialog.directory_name() == str(directory)
    dialog.close()
