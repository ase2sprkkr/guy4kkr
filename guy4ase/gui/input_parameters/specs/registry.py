"""Registry of Guided SPR-KKR tasks and their workflow presentation."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from . import arpes, bsf, dos, jxc, scf, xas
from .schema import TaskDialogSpec


class WorkflowStage(Enum):
    """High-level Guided workflow stage at which a task is recommended."""

    SCF = "scf"
    POST_SCF = "post_scf"


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Guy4ASE-owned metadata for one backend task with a Guided setup."""

    task: str
    spec_builder: Callable[[bool], TaskDialogSpec]
    workflow_stage: WorkflowStage
    workflow_label: str
    workflow_description: str

    def build_spec(self, *, is_2d: bool = False) -> TaskDialogSpec:
        spec = self.spec_builder(is_2d)
        if spec.task.lower() != self.task:
            raise ValueError(
                f"Guided task {self.task!r} built a spec for {spec.task!r}."
            )
        spec.primary_pages()
        return spec


_TASKS = (
    GuidedTaskDefinition(
        "scf",
        scf.build_spec,
        WorkflowStage.SCF,
        "Converge SCF",
        "Prepare and run a self-consistent calculation",
    ),
    GuidedTaskDefinition(
        "xas",
        xas.build_spec,
        WorkflowStage.POST_SCF,
        "Calculate XAS",
        "X-ray absorption spectroscopy",
    ),
    GuidedTaskDefinition(
        "arpes",
        arpes.build_spec,
        WorkflowStage.POST_SCF,
        "Calculate ARPES",
        "Angle-resolved photoemission spectroscopy",
    ),
    GuidedTaskDefinition(
        "dos",
        dos.build_spec,
        WorkflowStage.POST_SCF,
        "Calculate DOS",
        "Electronic density of states",
    ),
    GuidedTaskDefinition(
        "bsf",
        bsf.build_spec,
        WorkflowStage.POST_SCF,
        "Calculate BSF",
        "Bloch spectral function along an E–k path or on a k–k plane",
    ),
    GuidedTaskDefinition(
        "jxc",
        jxc.build_spec,
        WorkflowStage.POST_SCF,
        "Calculate JXC",
        "Exchange coupling and Dzyaloshinskii–Moriya interactions",
    ),
)
_TASKS_BY_NAME = {definition.task: definition for definition in _TASKS}


def guided_task_definition(task: str) -> GuidedTaskDefinition:
    """Return Guy4ASE metadata for a task supported by the Guided UI."""
    normalized = str(task).strip().lower()
    try:
        return _TASKS_BY_NAME[normalized]
    except KeyError as exc:
        raise ValueError(
            f"No guided setup is defined for task {str(task).upper()}."
        ) from exc


def guided_task_definitions() -> tuple[GuidedTaskDefinition, ...]:
    """Return all Guided task definitions in workflow presentation order."""
    return _TASKS


def workflow_task_definitions(
    stage: WorkflowStage,
) -> Iterable[GuidedTaskDefinition]:
    """Iterate Guided tasks recommended for one workflow stage."""
    return (definition for definition in _TASKS if definition.workflow_stage is stage)


def is_guided_task(task: str) -> bool:
    """Return whether Guy4ASE provides a Guided editor for ``task``."""
    return str(task).strip().lower() in _TASKS_BY_NAME


def task_dialog_spec(task: str, *, is_2d: bool = False) -> TaskDialogSpec:
    """Build and validate the declarative Guided layout for ``task``."""
    return guided_task_definition(task).build_spec(is_2d=is_2d)
