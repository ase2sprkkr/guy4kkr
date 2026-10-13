"""Regression tests for access to persistent calculation jobs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.main import GuiApplication


def test_workflow_job_entry_is_available_without_workspace_results(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    window = gui.create_workflow_window()

    assert not gui.controller.result_store.results
    assert not window._result_actions.isHidden()
    assert window._result_actions_widget._history_button is not None
    assert window._result_actions_widget._history_button.text() == (
        "Browse calculation jobs…"
    )
    window.close()
