from __future__ import annotations

from dataclasses import dataclass

import pytest
from ase import Atoms

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_model import (
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    EmptySphereUpdate,
    Load,
    LoadKind,
    RunTask,
    ScfProgress,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    WorkflowSection,
)
from guy4ase.gui.application.workflow_planner import (
    WorkflowPlanner,
    classify_scf_progress,
)
from guy4ase.gui.application.workspace import WorkspaceState


@dataclass
class Workspace:
    atoms: object | None = None
    status: str | None = None
    converged: bool = False
    kind: str | None = "3d"
    build_2d: bool = False
    empty_spheres: object | None = None
    vacuum_sites: bool = False
    restart_required: bool = False

    def structure_kind(self):
        return self.kind

    def can_build_2d(self):
        return self.build_2d

    def scf_status(self):
        return self.status

    def is_scf_converged(self):
        return self.converged

    def has_vacuum_sites(self):
        return self.vacuum_sites

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


def test_single_planner_owns_calculation_order_and_registry_task_order():
    before = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), empty_spheres=object())
    )
    assert _commands(before, WorkflowSection.CALCULATE) == (
        UpdateEmptySpheres(EmptySphereUpdate.RECALCULATE),
        RunTask("scf"),
    )

    after = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    assert _commands(after, WorkflowSection.CALCULATE) == (
        RunTask("xas"),
        RunTask("arpes"),
        RunTask("dos"),
        RunTask("bsf"),
        RunTask("jxc"),
    )


def test_registry_presentation_text_is_used_without_local_task_catalogue():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    dos = next(
        action
        for action in calculate.actions
        if action.command == RunTask("dos")
    )
    assert dos.title == "Calculate DOS"
    assert dos.description == "Electronic density of states"


def test_interrupted_scf_preserves_exact_stage_in_contextual_text():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), status="ITR-L-BULK")
    )

    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    scf = next(
        action
        for action in calculate.actions
        if action.command == RunTask("scf")
    )
    assert scf.title == "Continue SCF"
    assert scf.description == (
        "Resume from converging left bulk using the current potential"
    )


def test_initial_2d_scf_uses_contextual_description():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), kind="2d")
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    scf = next(
        action
        for action in calculate.actions
        if action.command == RunTask("scf")
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


def test_vacuum_sites_suppress_add_empty_spheres():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), vacuum_sites=True)
    )
    assert all(
        not isinstance(command, UpdateEmptySpheres)
        for command in _commands(plan, WorkflowSection.CALCULATE)
    )


def test_restart_required_suppresses_empty_sphere_update():
    plan = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            status="ITR",
            empty_spheres=object(),
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
        if action.command == RunTask("scf")
    )
    assert scf.title == "Converge SCF"
    assert UseForNewCalculation() not in _commands(plan, WorkflowSection.OTHER)
    assert _commands(plan, WorkflowSection.OTHER)[-1] == StartOver()
