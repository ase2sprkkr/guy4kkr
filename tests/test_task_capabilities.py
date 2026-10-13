from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.main import GuiApplication


class _Parameters:
    def __init__(self, task_name: str) -> None:
        self.task_name = task_name

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.task_name)

    def to_string(self, *, validate: bool = False) -> str:
        return f"TASK {self.task_name.upper()}"


def _scf_atoms(status="CONVERGED"):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(
        SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
    )
    return atoms


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


def test_use_for_new_calculation_disables_post_scf_current_task():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=_scf_atoms(),
            input_parameters=_Parameters("dos"),
            directory="calculation",
        )
    )

    assert controller.can_run_task("dos")
    assert controller.can_calculate()

    controller.use_for_new_calculation(expected_generation=controller.generation)

    assert controller.scf_status() == "START"
    assert not controller.can_run_task("dos")
    assert not controller.can_calculate()


def test_run_calculation_enforces_task_capability_at_launch_boundary(
    monkeypatch, tmp_path
):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=_Parameters("dos"),
            directory=str(tmp_path),
        )
    )
    messages = []
    constructed = []
    monkeypatch.setattr(
        calculation_flow.QMessageBox,
        "information",
        lambda parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        calculation_flow,
        "SprkkrRunWindow",
        lambda **kwargs: constructed.append(kwargs),
    )

    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
    ) is None
    assert constructed == []
    assert messages == [
        ("Task Not Available", "DOS cannot be run with the current workspace state.")
    ]


def test_expert_run_action_uses_current_task_capability(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(),
        recent_files_path=tmp_path / "recent.json",
    )
    expert = gui.create_main_window()
    expert.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    expert.controller.change_directory(str(tmp_path))
    expert.controller.replace_input_parameters(_Parameters("dos"))
    application.processEvents()

    assert not expert.run_calculation_action.isEnabled()

    expert.controller.replace_input_parameters(_Parameters("scf"))
    application.processEvents()

    assert expert.run_calculation_action.isEnabled()
    expert.close()


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
