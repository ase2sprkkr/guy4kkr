"""Regression tests for the application-owned project browser entry point."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import guy4ase.main as main_module
from guy4ase.gui.application.projects import ProjectRepository
from guy4ase.main import GuiApplication


def test_workflow_project_entry_is_separate_from_workspace_results(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=object(),
        project_repository=ProjectRepository(tmp_path / "projects"),
    )
    window = gui.create_workflow_window()

    assert not gui.controller.result_store.results
    assert window.browser_panel.project_browser_button.text() == "Project Browser…"
    window.close()


def test_project_browser_lifecycle_belongs_to_application(monkeypatch, tmp_path):
    _application = QApplication.instance() or QApplication([])
    events: list[tuple[str, object]] = []

    class _Signal:
        def __init__(self) -> None:
            self._callbacks = []

        def connect(self, callback) -> None:
            self._callbacks.append(callback)

        def emit(self) -> None:
            for callback in tuple(self._callbacks):
                callback()

    class FakeProjectBrowserDialog:
        instances: list["FakeProjectBrowserDialog"] = []

        def __init__(self, repository, job_source) -> None:
            self.repository = repository
            self.job_source = job_source
            self.destroyed = _Signal()
            self.delete_on_close = False
            type(self).instances.append(self)

        def setAttribute(self, attribute) -> None:
            self.delete_on_close = attribute == main_module.Qt.WidgetAttribute.WA_DeleteOnClose

        def show(self) -> None:
            events.append(("show", self))

        def raise_(self) -> None:
            events.append(("raise", self))

        def activateWindow(self) -> None:
            events.append(("activate", self))

        def close(self) -> None:
            self.destroyed.emit()

    monkeypatch.setattr(main_module, "ProjectBrowserDialog", FakeProjectBrowserDialog)
    repository = ProjectRepository(tmp_path / "projects")
    job_source = object()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=job_source,
        project_repository=repository,
    )
    workflow = gui.create_workflow_window()
    expert = gui.create_main_window()

    workflow.browser_panel.project_browser_button.click()
    first_dialog = FakeProjectBrowserDialog.instances[0]
    expert.browser_panel.project_browser_button.click()

    assert len(FakeProjectBrowserDialog.instances) == 1
    assert first_dialog.repository is repository
    assert first_dialog.job_source is job_source
    assert first_dialog.delete_on_close
    assert [name for name, _dialog in events] == [
        "show",
        "raise",
        "activate",
        "show",
        "raise",
        "activate",
    ]
    assert all(dialog is first_dialog for _name, dialog in events)

    first_dialog.close()
    workflow.browser_panel.project_browser_button.click()

    assert len(FakeProjectBrowserDialog.instances) == 2
    second_dialog = FakeProjectBrowserDialog.instances[1]
    assert second_dialog is not first_dialog
    assert second_dialog.delete_on_close
    assert events[-3:] == [
        ("show", second_dialog),
        ("raise", second_dialog),
        ("activate", second_dialog),
    ]

    workflow.close()
    expert.close()
