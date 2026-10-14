from __future__ import annotations

from dataclasses import dataclass

from guy4ase.gui.application.workflow_facts import EmptySpheresAction, ScfProgress
from guy4ase.gui.application.workflow_presentation import (
    WorkflowCommand,
    WorkflowCommandKind,
    WorkflowSection,
)
from guy4ase.gui.application.workflow_task_planner import (
    GuidedTaskSource,
    GuidedWorkflowPlanner,
    task_actions,
)


@dataclass(frozen=True)
class TaskPresentation:
    label: str
    description: str


@dataclass(frozen=True)
class TaskDefinition:
    task: str
    workflow: TaskPresentation


class Atoms:
    def get_chemical_formula(self):
        return "Fe"


class Workspace:
    def __init__(
        self,
        *,
        progress=ScfProgress.NOT_STARTED,
        structure_kind="3d",
        empty_spheres=None,
    ):
        self.atoms = Atoms()
        self._progress = progress
        self._structure_kind = structure_kind
        self._empty_spheres = empty_spheres

    def scf_progress(self):
        return self._progress

    def structure_kind(self):
        return self._structure_kind

    def can_build_2d(self):
        return self._structure_kind == "3d"

    def empty_spheres_action(self):
        return self._empty_spheres

    def structure_change_requires_scf_restart(self):
        return False


def _source(*definitions):
    def recommended(definition, *, has_structure, scf_converged):
        assert has_structure
        if definition.task == "scf":
            return not scf_converged
        return scf_converged

    return GuidedTaskSource.from_iterable(definitions, recommended)


def test_task_actions_follow_registry_order_without_local_task_catalogue():
    source = _source(
        TaskDefinition("dos", TaskPresentation("DOS", "Density of states")),
        TaskDefinition("bsf", TaskPresentation("BSF", "Bloch spectral function")),
    )

    actions = task_actions(
        Workspace(progress=ScfProgress.CONVERGED),
        source,
    )

    assert tuple(action.command for action in actions) == (
        WorkflowCommand(WorkflowCommandKind.RUN_TASK, "dos"),
        WorkflowCommand(WorkflowCommandKind.RUN_TASK, "bsf"),
    )
    assert tuple(action.title for action in actions) == ("DOS", "BSF")


def test_task_recommendation_policy_is_external_to_workspace_capabilities():
    source = _source(
        TaskDefinition("scf", TaskPresentation("Converge SCF", "Run SCF")),
        TaskDefinition("dos", TaskPresentation("DOS", "Density of states")),
    )

    actions = task_actions(
        Workspace(progress=ScfProgress.NOT_STARTED),
        source,
    )

    assert tuple(action.command.minor for action in actions) == ("scf",)


def test_interrupted_scf_is_contextualized_without_changing_registry_metadata():
    definition = TaskDefinition(
        "scf",
        TaskPresentation("Converge SCF", "Prepare and run SCF"),
    )
    actions = task_actions(
        Workspace(progress=ScfProgress.LEFT_BULK),
        _source(definition),
    )

    assert len(actions) == 1
    assert actions[0].title == "Continue SCF"
    assert "current potential" in actions[0].description
    assert definition.workflow.label == "Converge SCF"


def test_initial_2d_scf_uses_contextual_description():
    actions = task_actions(
        Workspace(
            progress=ScfProgress.NOT_STARTED,
            structure_kind="2d",
        ),
        _source(
            TaskDefinition(
                "scf",
                TaskPresentation("Converge SCF", "Prepare and run SCF"),
            )
        ),
    )

    assert actions[0].description == (
        "Converge bulk region(s), then the interaction zone"
    )


def test_complete_planner_appends_tasks_after_empty_spheres():
    source = _source(
        TaskDefinition("scf", TaskPresentation("Converge SCF", "Run SCF")),
    )
    planner = GuidedWorkflowPlanner(source)

    plan = planner.for_workspace(
        Workspace(
            progress=ScfProgress.NOT_STARTED,
            empty_spheres=EmptySpheresAction.ADD,
        )
    )

    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    assert tuple(action.command.kind for action in calculate.actions) == (
        WorkflowCommandKind.UPDATE_EMPTY_SPHERES,
        WorkflowCommandKind.RUN_TASK,
    )


def test_complete_planner_creates_calculate_group_when_only_tasks_are_present():
    planner = GuidedWorkflowPlanner(
        _source(
            TaskDefinition("dos", TaskPresentation("DOS", "Density of states")),
        )
    )

    plan = planner.for_workspace(Workspace(progress=ScfProgress.CONVERGED))

    assert plan.groups[0].section is WorkflowSection.CALCULATE
    assert plan.groups[0].actions[0].command == WorkflowCommand(
        WorkflowCommandKind.RUN_TASK,
        "dos",
    )
