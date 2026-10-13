from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.main import GuiApplication


def _action_title(widget):
    return str(widget.property("workflowActionTitle") or widget.text().splitlines()[0])


def _calculate_actions(window):
    layout = window._action_group_layouts.get(window._GROUP_CALCULATE)
    if layout is None:
        return []
    return [
        _action_title(layout.itemAt(index).widget())
        for index in range(1, layout.count())
    ]


def test_controller_owns_task_capability_policy():
    controller = WorkspaceController()

    assert not controller.can_run_task("scf")
    assert not controller.can_run_task("dos")

    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    controller.replace_structure(atoms)

    assert controller.can_run_task("SCF")
    assert not controller.can_run_task("dos")
    assert not controller.can_run_task("xas")
    assert not controller.can_run_task("unknown")

    controller.is_scf_converged = lambda: True
    for task in ("xas", "arpes", "dos", "bsf", "jxc"):
        assert controller.can_run_task(task)


def test_workflow_filters_each_task_through_controller_capability(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(),
        recent_files_path=tmp_path / "recent.json",
    )
    window = gui.create_workflow_window()
    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    window.controller.is_scf_converged = lambda: False
    window.controller.can_run_task = lambda task: str(task).lower() in {"scf", "dos"}

    window._refresh()
    application.processEvents()
    actions = _calculate_actions(window)

    assert "Converge SCF" in actions
    assert "Calculate DOS" in actions
    assert "Calculate XAS" not in actions
    assert "Calculate ARPES" not in actions
    assert "Calculate BSF" not in actions
    assert "Calculate JXC" not in actions
    window.close()
