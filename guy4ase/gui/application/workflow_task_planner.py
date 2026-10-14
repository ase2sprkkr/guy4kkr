"""Compose central Guided task metadata into workflow presentation plans.

This module deliberately depends on protocols instead of the concrete task
registry. The task-definition branch can therefore provide its ordered registry
and recommendation policy without the workflow planner owning a duplicate task
catalogue or importing input-editor implementation details.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Protocol

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_facts import ScfProgress
from guy4ase.gui.application.workflow_presentation import (
    ActionIcon,
    ActionStyle,
    AvailableAction,
    AvailableActionGroup,
    WorkflowCommand,
    WorkflowCommandKind,
    WorkflowPlan,
    WorkflowPlanner,
    WorkflowSection,
    WorkflowWorkspace,
)


class WorkflowTaskPresentation(Protocol):
    """Task metadata required by Guided workflow presentation."""

    label: str
    description: str


class WorkflowTaskDefinition(Protocol):
    """Ordered registry item required by the workflow planner."""

    task: str
    workflow: WorkflowTaskPresentation


class TaskWorkflowWorkspace(WorkflowWorkspace, Protocol):
    """Additional workspace facts required for contextual task text."""

    def structure_kind(self) -> str | None: ...


class TaskRecommendation(Protocol):
    """Guided recommendation policy supplied by the task/application layer."""

    def __call__(
        self,
        definition: WorkflowTaskDefinition,
        *,
        has_structure: bool,
        scf_converged: bool,
    ) -> bool: ...


@dataclass(frozen=True)
class GuidedTaskSource:
    """Ordered task registry plus its Guided recommendation policy."""

    definitions: tuple[WorkflowTaskDefinition, ...]
    is_recommended: TaskRecommendation

    @classmethod
    def from_iterable(
        cls,
        definitions: Iterable[WorkflowTaskDefinition],
        is_recommended: TaskRecommendation,
    ) -> "GuidedTaskSource":
        return cls(tuple(definitions), is_recommended)


def _task_action(
    definition: WorkflowTaskDefinition,
    workspace: TaskWorkflowWorkspace,
    progress: ScfProgress,
) -> AvailableAction:
    task = definition.task
    title = definition.workflow.label
    description = definition.workflow.description

    if task == "scf":
        if progress.can_continue:
            title = "Continue SCF"
            description = "Resume the interrupted SCF sequence using the current potential"
        elif workspace.structure_kind() == "2d":
            description = "Converge bulk region(s), then the interaction zone"

    return AvailableAction(
        command=WorkflowCommand(WorkflowCommandKind.RUN_TASK, task),
        title=title,
        description=description,
        style=ActionStyle.CALCULATION,
        icon=ActionIcon.RUN,
    )


def task_actions(
    workspace: TaskWorkflowWorkspace,
    source: GuidedTaskSource,
) -> tuple[AvailableAction, ...]:
    """Return recommended task actions in registry-defined order."""
    if workspace.atoms is None:
        return ()

    progress = workspace.scf_progress()
    converged = progress is ScfProgress.CONVERGED
    return tuple(
        _task_action(definition, workspace, progress)
        for definition in source.definitions
        if source.is_recommended(
            definition,
            has_structure=True,
            scf_converged=converged,
        )
    )


def _with_calculation_actions(
    plan: WorkflowPlan,
    task_items: tuple[AvailableAction, ...],
) -> WorkflowPlan:
    if not task_items:
        return plan

    groups = list(plan.groups)
    for index, group in enumerate(groups):
        if group.section is WorkflowSection.CALCULATE:
            groups[index] = replace(
                group,
                actions=group.actions + task_items,
            )
            break
    else:
        groups.insert(
            0,
            AvailableActionGroup(
                section=WorkflowSection.CALCULATE,
                title="Calculate",
                actions=task_items,
            ),
        )
    return replace(plan, groups=tuple(groups))


class GuidedWorkflowPlanner:
    """Complete workflow planner composed with an external Guided task source."""

    def __init__(self, tasks: GuidedTaskSource) -> None:
        self._tasks = tasks

    def for_workspace(
        self,
        workspace: TaskWorkflowWorkspace,
        *,
        recent: RecentLaunch | None = None,
    ) -> WorkflowPlan:
        plan = WorkflowPlanner.for_workspace(workspace, recent=recent)
        return _with_calculation_actions(
            plan,
            task_actions(workspace, self._tasks),
        )
