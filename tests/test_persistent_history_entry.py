"""Regression tests for access to persistent calculation jobs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import guy4ase.main as main_module
from guy4ase.main import GuiApplication


def test_workflow_job_entry_is_separate_from_workspace_results(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    window = gui.create_workflow_window()

    assert not gui.controller.result_store.results
    assert window.browser_panel.calculation_jobs_button.text() == "Calculation Jobs…"
    window.close()


def test_calculation_history_lifecycle_belongs_to_application(monkeypatch, tmp_path):
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

    class FakeHistoryDialog:
        instances: list["FakeHistoryDialog"] = []

        def __init__(self) -> None:
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

    monkeypatch.setattr(main_module, "CalculationHistoryDialog", FakeHistoryDialog)
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    workflow = gui.create_workflow_window()
    expert = gui.create_main_window()

    workflow.browser_panel.calculation_jobs_button.click()
    first_dialog = FakeHistoryDialog.instances[0]
    expert.browser_panel.calculation_jobs_button.click()

    assert len(FakeHistoryDialog.instances) == 1
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
    workflow.browser_panel.calculation_jobs_button.click()

    assert len(FakeHistoryDialog.instances) == 2
    second_dialog = FakeHistoryDialog.instances[1]
    assert second_dialog is not first_dialog
    assert second_dialog.delete_on_close
    assert events[-3:] == [
        ("show", second_dialog),
        ("raise", second_dialog),
        ("activate", second_dialog),
    ]

    workflow.close()
    expert.close()
