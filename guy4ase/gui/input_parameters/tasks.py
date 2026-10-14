"""Guy4ASE metadata for backend tasks exposed through the Guided UI."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from guy4ase.gui.input_parameters.specs import arpes, bsf, dos, jxc, scf, xas
from guy4ase.gui.input_parameters.specs.schema import TaskDialogSpec


class WorkflowStage(Enum):
    """High-level workflow stage at which a Guided task is presented."""

    SCF = "scf"
    POST_SCF = "post_scf"


@dataclass(frozen=True)
class WorkflowPresentation:
    """Workflow-only presentation metadata for a Guided task."""

    label: str
    description: str
    stage: WorkflowStage


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Guy4ASE-owned metadata for one backend task with a Guided editor."""

    backend_task: str
    spec_builder: Callable[[bool], TaskDialogSpec]
    workflow: WorkflowPresentation

    def build_spec(self, *, is_2d: bool = False) -> TaskDialogSpec:
        spec = self.spec_builder(is_2d)
        spec.primary_pages()
        return spec


_TASKS = (
    GuidedTaskDefinition(
        "scf",
        scf.build_spec,
        WorkflowPresentation(
            "Converge SCF",
            "Prepare and run a self-consistent calculation",
            WorkflowStage.SCF,
        ),
    ),
    GuidedTaskDefinition(
        "xas",
        xas.build_spec,
        WorkflowPresentation(
            "Calculate XAS",
            "X-ray absorption spectroscopy",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "arpes",
        arpes.build_spec,
        WorkflowPresentation(
            "Calculate ARPES",
            "Angle-resolved photoemission spectroscopy",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "dos",
        dos.build_spec,
        WorkflowPresentation(
            "Calculate DOS",
            "Electronic density of states",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "bsf",
        bsf.build_spec,
        WorkflowPresentation(
            "Calculate BSF",
            "Bloch spectral function along an E–k path or on a k–k plane",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "jxc",
        jxc.build_spec,
        WorkflowPresentation(
            "Calculate JXC",
            "Exchange coupling and Dzyaloshinskii–Moriya interactions",
            WorkflowStage.POST_SCF,
        ),
    ),
)
_TASKS_BY_BACKEND_TASK = {
    definition.backend_task: definition for definition in _TASKS
}


def guided_task_definition(task: str) -> GuidedTaskDefinition:
    """Return Guy4ASE metadata for a task supported by the Guided UI."""
    normalized = str(task).strip().lower()
    try:
        return _TASKS_BY_BACKEND_TASK[normalized]
    except KeyError as exc:
        raise ValueError(
            f"No guided setup is defined for task {str(task).upper()}."
        ) from exc


def guided_task_definitions() -> tuple[GuidedTaskDefinition, ...]:
    """Return all Guided task definitions in presentation order."""
    return _TASKS


def is_guided_task(task: str) -> bool:
    """Return whether Guy4ASE provides a Guided editor for ``task``."""
    return str(task).strip().lower() in _TASKS_BY_BACKEND_TASK


def workflow_tasks(stage: WorkflowStage) -> tuple[GuidedTaskDefinition, ...]:
    """Return tasks presented at ``stage``.

    This is presentation policy only. It must never be used as a backend launch
    restriction: Expert mode may run any task accepted by ASE2SPRKKR.
    """
    return tuple(
        definition for definition in _TASKS if definition.workflow.stage is stage
    )
