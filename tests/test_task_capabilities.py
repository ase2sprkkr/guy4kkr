from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.calculation_policy import guided_task_is_recommended
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    guided_task_definition,
    guided_task_definitions,
)
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


def test_controller_calculation_readiness_is_task_agnostic(tmp_path):
    controller = WorkspaceController()
    assert not controller.can_calculate()

    controller.replace_structure(Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    controller.change_directory(str(tmp_path))
    controller.replace_input_parameters(_Parameters("torque"))

    assert controller.can_calculate()


def test_use_for_new_calculation_does_not_block_backend_task():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=_scf_atoms(),
            input_parameters=_Parameters("dos"),
            directory="calculation",
        )
    )

    assert controller.can_calculate()

    controller.use_for_new_calculation(expected_generation=controller.generation)

    assert controller.scf_status() == "START"
    assert controller.can_calculate()


def test_run_calculation_does_not_apply_guided_recommendation_at_launch_boundary(
    monkeypatch, tmp_path
):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=_Parameters("dos"),
            directory=str(tmp_path),
        )
    )
    constructed = []

    class FakeRunWindow:
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)

        def show(self) -> None:
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", FakeRunWindow)

    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
    )

    assert isinstance(window, FakeRunWindow)
    assert len(constructed) == 1
    assert constructed[0]["request"].input_parameters.task_name == "dos"


def test_expert_run_action_accepts_backend_task_without_guided_registration(tmp_path):
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
    expert.controller.replace_input_parameters(_Parameters("torque"))
    application.processEvents()

    assert expert.run_calculation_action.isEnabled()
    expert.close()


def test_guided_task_registry_owns_workflow_metadata():
    definitions = guided_task_definitions()

    assert tuple(definition.task for definition in definitions) == (
        "scf",
        "xas",
        "arpes",
        "dos",
        "bsf",
        "jxc",
    )
    assert guided_task_definition("DOS").workflow.label == "Calculate DOS"
    assert guided_task_definition("scf").workflow.stage is WorkflowStage.SCF
    assert guided_task_definition("dos").workflow.stage is WorkflowStage.POST_SCF


def test_guided_policy_interprets_workflow_stage():
    scf = guided_task_definition("scf")
    dos = guided_task_definition("dos")

    assert not guided_task_is_recommended(
        scf,
        has_structure=False,
        scf_converged=False,
    )
    assert guided_task_is_recommended(
        scf,
        has_structure=True,
        scf_converged=False,
    )
    assert not guided_task_is_recommended(
        dos,
        has_structure=True,
        scf_converged=False,
    )
    assert guided_task_is_recommended(
        dos,
        has_structure=True,
        scf_converged=True,
    )


def test_workflow_uses_guided_registry_and_recommendation_policy(tmp_path):
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
    window._refresh()
    application.processEvents()
    actions = _calculate_actions(window)
    assert "Converge SCF" in actions
    for definition in guided_task_definitions():
        if definition.workflow.stage is WorkflowStage.POST_SCF:
            assert definition.workflow.label not in actions

    window.controller.is_scf_converged = lambda: True
    window._refresh()
    application.processEvents()
    actions = _calculate_actions(window)
    assert "Converge SCF" not in actions
    for definition in guided_task_definitions():
        if definition.workflow.stage is WorkflowStage.POST_SCF:
            assert definition.workflow.label in actions

    window.close()
