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
from guy4ase.gui.input_parameters.specs.registry import (
    WorkflowStage,
    guided_task_definition,
    guided_task_definitions,
    workflow_task_definitions,
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


def test_guided_registry_owns_task_mapping_and_workflow_metadata():
    definitions = guided_task_definitions()

    assert [definition.task for definition in definitions] == [
        "scf",
        "xas",
        "arpes",
        "dos",
        "bsf",
        "jxc",
    ]
    assert guided_task_definition("DOS").parameter_task == "dos"
    assert [
        definition.task
        for definition in workflow_task_definitions(WorkflowStage.POST_SCF)
    ] == ["xas", "arpes", "dos", "bsf", "jxc"]
    assert all(definition.build_spec().title for definition in definitions)


def test_controller_calculation_readiness_is_task_agnostic():
    controller = WorkspaceController()
    assert not controller.can_calculate()

    controller.replace_structure(Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    controller.change_directory("calculation")
    controller.replace_input_parameters(_Parameters("torque"))

    assert controller.can_calculate()


def test_use_for_new_calculation_does_not_hard_block_current_task():
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


def test_run_calculation_does_not_enforce_guided_workflow_stage(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=_Parameters("torque"),
            directory=str(tmp_path),
        )
    )

    class RunWindow:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.shown = False

        def show(self):
            self.shown = True

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", RunWindow)
    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
    )

    assert isinstance(window, RunWindow)
    assert window.shown
    assert window.kwargs["request"].input_parameters.task_name == "torque"


def test_expert_run_action_is_not_limited_to_guided_tasks(tmp_path):
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


def test_workflow_uses_registry_as_post_scf_recommendation(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(),
        recent_files_path=tmp_path / "recent.json",
    )
    window = gui.create_workflow_window()

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    window._refresh()
    application.processEvents()
    actions = _calculate_actions(window)
    assert "Converge SCF" in actions
    for definition in workflow_task_definitions(WorkflowStage.POST_SCF):
        assert definition.workflow_label not in actions

    window.controller.replace_structure(_scf_atoms())
    window._refresh()
    application.processEvents()
    actions = _calculate_actions(window)
    assert "Converge SCF" not in actions
    for definition in workflow_task_definitions(WorkflowStage.POST_SCF):
        assert definition.workflow_label in actions
    window.close()
