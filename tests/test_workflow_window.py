import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.workflow_window import WorkflowWindow


def _action_titles(window):
    return [
        window._actions_layout.itemAt(index).widget().text().splitlines()[0]
        for index in range(window._actions_layout.count())
    ]


def test_load_output_is_only_available_on_the_start_screen():
    application = QApplication.instance() or QApplication([])
    window = WorkflowWindow()

    assert "Load SPR-KKR Output" in _action_titles(window)

    window.expert_window.set_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()

    assert "Load SPR-KKR Output" not in _action_titles(window)
    window.close()
