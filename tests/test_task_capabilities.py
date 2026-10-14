from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.task_policy import is_guided_task_recommended
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.input_parameters.specs.registry import (
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


def test_guided_registry_owns_supported_task_identity_and_metadata():
    definitions = guided_task_definitions()

    assert definitions
    assert len({definition.task for definition in definitions}) == len(definitions)
    for definition in definitions:
        backend = InputParameters.definition(definition.backend_task)
        assert backend.name.lower() == definition.backend_task
        assert definition.dialog_spec().pages
        assert definition.workflow_title
        assert definition.workflow_description

    assert guided_task_definition("DOS").workflow_title == "Calculate DOS"


def test_workflow_policy_is_recommendation_not_launch_capability():
    scf = guided_task_definition("scf")
    dos = guided_task_definition("dos")

    assert is_guided_task_recommended(
        scf, has_structure=True, scf_converged=False
    )
    assert not is_guided_task_recommended(
        dos, has_structure=True, scf_converged=False
    )
    assert is_guided_task_recommended(
        dos, has_structure=True, scf_converged=True
    )
    assert not is_guided_task_recommended(
        scf, has_structure=False, scf_converged=False
    )


def test_controller_calculation_readiness_does_not_encode_task_policy():
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


def test_run_calculation_does_not_reject_non_guided_task(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=_Parameters("torque"),
            directory=str(tmp_path),
        )
    )
    constructed = []

    class FakeRunWindow:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def show(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", FakeRunWindow)
    monkeypatch.setattr(
        calculation_flow,
        "_position_like_window",
        lambda _window, _window_id: None,
    )

    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
    )

    assert isinstance(window, FakeRunWindow)
    assert constructed[0]["request"].input_parameters.task_name == "torque"


def test_expert_run_action_depends_on_workspace_readiness_not_guided_registry(tmp_path):
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


def test_workflow_uses_registry_and_policy_for_calculation_cards(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(),
        recent_files_path=tmp_path / "recent.json",
    )
    window = gui.create_workflow_window()

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    actions = set(_calculate_actions(window))
    post_scf_titles = {
        definition.workflow_title
        for definition in guided_task_definitions()
        if definition.workflow_stage is WorkflowStage.POST_SCF
    }

    assert guided_task_definition("scf").workflow_title in actions
    assert actions.isdisjoint(post_scf_titles)

    window.controller.replace_structure(_scf_atoms())
    application.processEvents()
    actions = set(_calculate_actions(window))

    assert guided_task_definition("scf").workflow_title not in actions
    assert post_scf_titles <= actions
    window.close()
