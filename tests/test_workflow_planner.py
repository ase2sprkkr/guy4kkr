from __future__ import annotations

from dataclasses import dataclass

import pytest
from ase import Atoms

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_model import (
    ActionIcon,
    ActionStyle,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    ScfProgress,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    WorkflowPlan,
    WorkflowSection,
)
from guy4ase.gui.application.workflow_planner import (
    WorkflowPlanner,
    classify_scf_progress,
)
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_actions import EmptySpheresAction
from guy4ase.gui.input_parameters.tasks import (
    GuidedTaskDefinition,
    guided_task_definition,
)


@dataclass
class Workspace:
    atoms: object | None = None
    status: str | None = None
    converged: bool = False
    kind: str | None = "3d"
    build_2d: bool = False
    spheres_action: EmptySpheresAction | None = None
    restart_required: bool = False

    def structure_kind(self):
        return self.kind

    def can_build_2d(self):
        return self.build_2d

    def scf_status(self):
        return self.status

    def is_scf_converged(self):
        return self.converged

    def empty_spheres_action(self):
        return self.spheres_action

    def structure_change_requires_scf_restart(self):
        return self.restart_required


class FormulaAtoms:
    def __init__(self, formula="Fe"):
        self.formula = formula

    def get_chemical_formula(self):
        return self.formula


def _commands(plan, section):
    group = plan.group(section)
    return () if group is None else tuple(action.command for action in group.actions)


@pytest.mark.parametrize(
    ("status", "converged", "expected"),
    (
        (None, False, ScfProgress.NOT_STARTED),
        ("START", False, ScfProgress.NOT_STARTED),
        ("itr", False, ScfProgress.ITERATING),
        ("ITR-BULK", False, ScfProgress.BULK),
        ("ITR-L-BULK", False, ScfProgress.LEFT_BULK),
        ("ITR-R-BULK", False, ScfProgress.RIGHT_BULK),
        ("ITR-I-ZONE", False, ScfProgress.INTERACTION_ZONE),
        ("future-status", False, ScfProgress.UNKNOWN),
        ("ITR", True, ScfProgress.CONVERGED),
    ),
)
def test_classify_scf_progress(status, converged, expected):
    assert classify_scf_progress(status, converged=converged) is expected


def test_initial_plan_uses_typed_commands_and_recent_action():
    recent = RecentLaunch("output", "/tmp/scf.out")
    plan = WorkflowPlanner().initial_plan(recent)

    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CREATE,
        WorkflowSection.LOAD,
    )
    assert _commands(plan, WorkflowSection.CREATE) == (
        CreateStructure(CreateStructureKind.THREE_D),
        CreateStructure(CreateStructureKind.PROTOTYPE),
        CreateStructure(CreateStructureKind.SURFACE),
        CreateStructure(CreateStructureKind.TWO_D),
    )
    assert _commands(plan, WorkflowSection.LOAD) == (
        Load(LoadKind.ONLINE_STRUCTURE),
        Load(LoadKind.STRUCTURE),
        Load(LoadKind.OUTPUT),
        ContinueRecent(recent),
    )

    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    output = next(action for action in load.actions if action.command == Load(LoadKind.OUTPUT))
    continue_action = load.actions[-1]
    assert output.icon is ActionIcon.RESULT
    assert continue_action.description == ""
    assert continue_action.icon is ActionIcon.CONTINUE


def test_run_task_requires_canonical_guided_task_definition():
    scf = guided_task_definition("scf")
    command = RunTask(scf)

    assert isinstance(command.task, GuidedTaskDefinition)
    assert command.task is scf
    with pytest.raises(TypeError, match="GuidedTaskDefinition"):
        RunTask("scf")  # type: ignore[arg-type]


def test_single_planner_owns_calculation_order_and_registry_task_order():
    scf = guided_task_definition("scf")
    before = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            spheres_action=EmptySpheresAction.RECALCULATE,
        )
    )
    assert _commands(before, WorkflowSection.CALCULATE) == (
        UpdateEmptySpheres(),
        RunTask(scf),
    )

    after = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    assert _commands(after, WorkflowSection.CALCULATE) == tuple(
        RunTask(guided_task_definition(task))
        for task in ("xas", "arpes", "dos", "bsf", "jxc")
    )


def test_registry_presentation_text_is_used_without_local_task_catalogue():
    dos_definition = guided_task_definition("dos")
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    dos = next(
        action
        for action in calculate.actions
        if action.command == RunTask(dos_definition)
    )
    assert dos.title == dos_definition.workflow.label
    assert dos.description == dos_definition.workflow.description


def test_interrupted_scf_preserves_exact_stage_in_contextual_text():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), status="ITR-L-BULK")
    )

    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    scf = next(
        action
        for action in calculate.actions
        if action.command == RunTask(guided_task_definition("scf"))
    )
    assert scf.title == "Continue SCF"
    assert scf.description == (
        "Resume from converging left bulk using the current potential"
    )


def test_unknown_scf_status_remains_visible_for_forward_compatibility():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), status="future-status")
    )

    assert "SCF status: FUTURE-STATUS" in plan.subtitle
    assert UseForNewCalculation() in _commands(plan, WorkflowSection.OTHER)


def test_initial_2d_scf_uses_contextual_description():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), kind="2d")
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    scf = next(
        action
        for action in calculate.actions
        if action.command == RunTask(guided_task_definition("scf"))
    )
    assert scf.description == "Converge bulk region(s), then the interaction zone"


def test_active_3d_structure_uses_contextual_create_group_title():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), build_2d=True)
    )

    create = plan.group(WorkflowSection.CREATE)
    assert create is not None
    assert create.title == "Create derived structure"
    assert _commands(plan, WorkflowSection.CREATE) == (
        Build2D(Build2DKind.SURFACE),
        Build2D(Build2DKind.STRUCTURE),
    )


def test_empty_sphere_action_comes_from_workspace_policy():
    without_recommendation = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), spheres_action=None)
    )
    assert all(
        not isinstance(command, UpdateEmptySpheres)
        for command in _commands(without_recommendation, WorkflowSection.CALCULATE)
    )

    with_recommendation = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            spheres_action=EmptySpheresAction.ADD,
        )
    )
    assert _commands(with_recommendation, WorkflowSection.CALCULATE)[0] == (
        UpdateEmptySpheres()
    )


def test_restart_required_suppresses_empty_sphere_update():
    plan = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            status="ITR",
            spheres_action=EmptySpheresAction.RECALCULATE,
            restart_required=True,
        )
    )
    assert all(
        not isinstance(command, UpdateEmptySpheres)
        for command in _commands(plan, WorkflowSection.CALCULATE)
    )


def test_pending_workspace_restart_is_not_presented_as_interrupted_scf():
    state = WorkspaceState(atoms=Atoms("Fe"), restarted=True)
    workspace = Workspace(
        atoms=FormulaAtoms(),
        status=state.scf_status(),
        converged=state.is_scf_converged(),
    )

    plan = WorkflowPlanner().for_workspace(workspace)

    assert "SCF status: not converged" in plan.subtitle
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    scf = next(
        action
        for action in calculate.actions
        if action.command == RunTask(guided_task_definition("scf"))
    )
    assert scf.title == "Converge SCF"
    assert UseForNewCalculation() not in _commands(plan, WorkflowSection.OTHER)
    assert _commands(plan, WorkflowSection.OTHER)[-1] == StartOver()


def test_workflow_plan_rejects_duplicate_sections():
    action = AvailableAction(
        StartOver(),
        "Start Over",
        "Choose a different structure",
        ActionStyle.DESTRUCTIVE,
    )
    first = AvailableActionGroup(WorkflowSection.OTHER, "Other", (action,))
    second = AvailableActionGroup(WorkflowSection.OTHER, "Again", (action,))

    with pytest.raises(ValueError, match="each section at most once"):
        WorkflowPlan("subtitle", (first, second))
