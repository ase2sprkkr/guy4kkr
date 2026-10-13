from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.main import GuiApplication


def test_expert_result_actions_follow_workspace_state_change(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(atoms=Atoms("Fe"), potential_path="Fe.pot"),
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    window = gui.create_main_window()
    widget = window._result_actions_widget
    assert widget is not None
    previous_state = gui.controller.state_id
    assert widget._current_state_id == previous_state

    gui.controller.use_for_new_calculation(
        expected_generation=gui.controller.generation,
    )

    assert gui.controller.state_id != previous_state
    assert widget._current_state_id == gui.controller.state_id
    assert widget._current_structure_id == gui.controller.structure_id
    window.close()
