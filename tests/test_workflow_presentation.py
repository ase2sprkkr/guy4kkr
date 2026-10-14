from __future__ import annotations

from dataclasses import dataclass

import pytest

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_facts import EmptySpheresAction, ScfProgress
from guy4ase.gui.application.workflow_presentation import (
    ActionIcon,
    ActionStyle,
    AvailableAction,
    AvailableActionGroup,
    Build2DAction,
    CreateStructureAction,
    LoadAction,
    WorkflowCommand,
    WorkflowCommandKind,
    WorkflowPlanner,
    WorkflowSection,
)


class _Atoms:
    def __init__(self, formula="Fe"):
        self._formula = formula

    def get_chemical_formula(self):
        return self._formula


@dataclass
class _Workspace:
    atoms: object | None = None
    progress: ScfProgress = ScfProgress.NOT_STARTED
    build_2d: bool = False
    spheres: EmptySpheresAction | None = None
    restart_required: bool = False

    def scf_progress(self):
        return self.progress

    def can_build_2d(self):
        return self.build_2d

    def empty_spheres_action(self):
        return self.spheres

    def structure_change_requires_scf_restart(self):
        return self.restart_required


def test_available_action_accepts_existing_domain_enum_as_minor_command():
    action = AvailableAction(
        command=WorkflowCommand(
            WorkflowCommandKind.UPDATE_EMPTY_SPHERES,
            EmptySpheresAction.ADD,
        ),
        title="Do it",
        description="Use the existing domain command value",
        style=ActionStyle.STRUCTURE,
        icon=ActionIcon.EMPTY_SPHERES,
    )

    assert action.command.minor is EmptySpheresAction.ADD


def test_action_group_rejects_empty_groups():
    with pytest.raises(ValueError, match="must not be empty"):
        AvailableActionGroup(
            section=WorkflowSection.CALCULATE,
            title="Calculate",
            actions=(),
        )


def test_initial_plan_is_fully_grouped_and_ordered_for_the_view():
    plan = WorkflowPlanner.initial_plan()

    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CREATE,
        WorkflowSection.LOAD,
    )

    create = plan.group(WorkflowSection.CREATE)
    assert create is not None
    assert tuple(action.command for action in create.actions) == (
        WorkflowCommand(
            WorkflowCommandKind.CREATE_STRUCTURE, CreateStructureAction.THREE_D
        ),
        WorkflowCommand(
            WorkflowCommandKind.CREATE_STRUCTURE, CreateStructureAction.PROTOTYPE
        ),
        WorkflowCommand(
            WorkflowCommandKind.CREATE_STRUCTURE, CreateStructureAction.SURFACE
        ),
        WorkflowCommand(
            WorkflowCommandKind.CREATE_STRUCTURE, CreateStructureAction.TWO_D
        ),
    )

    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    assert tuple(action.command for action in load.actions) == (
        WorkflowCommand(WorkflowCommandKind.LOAD, LoadAction.ONLINE_STRUCTURE),
        WorkflowCommand(WorkflowCommandKind.LOAD, LoadAction.STRUCTURE),
        WorkflowCommand(WorkflowCommandKind.LOAD, LoadAction.OUTPUT),
    )


def test_initial_plan_appends_preferred_recent_launch_to_load_group():
    recent = RecentLaunch("output", "/tmp/scf.out")
    load = WorkflowPlanner.initial_plan(recent).group(WorkflowSection.LOAD)

    assert load is not None
    assert load.actions[-1].command == WorkflowCommand(
        WorkflowCommandKind.LOAD, recent
    )
    assert load.actions[-1].title == "Continue: scf.out"


def test_current_workspace_plan_owns_non_task_grouping_and_ordering():
    plan = WorkflowPlanner.for_workspace(
        _Workspace(
            atoms=_Atoms("Fe2"),
            spheres=EmptySpheresAction.ADD,
            build_2d=True,
        )
    )

    assert plan.subtitle == "Current structure: Fe2  •  SCF status: not converged"
    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CALCULATE,
        WorkflowSection.VIEW,
        WorkflowSection.CREATE,
        WorkflowSection.OTHER,
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    assert calculate.actions[0].command == WorkflowCommand(
        WorkflowCommandKind.UPDATE_EMPTY_SPHERES,
        EmptySpheresAction.ADD,
    )
    create = plan.group(WorkflowSection.CREATE)
    assert create is not None
    assert tuple(action.command.minor for action in create.actions) == (
        Build2DAction.SURFACE,
        Build2DAction.STRUCTURE,
    )
    other = plan.group(WorkflowSection.OTHER)
    assert other is not None
    assert tuple(action.command.kind for action in other.actions) == (
        WorkflowCommandKind.START_OVER,
    )


def test_interrupted_scf_plan_suppresses_spheres_when_restart_is_required():
    plan = WorkflowPlanner.for_workspace(
        _Workspace(
            atoms=_Atoms(),
            progress=ScfProgress.BULK,
            spheres=EmptySpheresAction.RECALCULATE,
            restart_required=True,
        )
    )

    assert plan.group(WorkflowSection.CALCULATE) is None
    other = plan.group(WorkflowSection.OTHER)
    assert other is not None
    assert tuple(action.command.kind for action in other.actions) == (
        WorkflowCommandKind.USE_FOR_NEW_CALCULATION,
        WorkflowCommandKind.START_OVER,
    )
    assert "converging bulk" in plan.subtitle


def test_converged_plan_never_offers_empty_sphere_update():
    plan = WorkflowPlanner.for_workspace(
        _Workspace(
            atoms=_Atoms(),
            progress=ScfProgress.CONVERGED,
            spheres=EmptySpheresAction.RECALCULATE,
        )
    )

    assert plan.group(WorkflowSection.CALCULATE) is None
    assert "CONVERGED" in plan.subtitle


def test_plan_group_returns_none_for_absent_section():
    plan = WorkflowPlanner.initial_plan()

    assert plan.group(WorkflowSection.CALCULATE) is None
