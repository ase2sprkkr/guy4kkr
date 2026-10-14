"""Single registry for tasks supported by Guy4ASE's guided workflow."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from . import arpes, bsf, dos, jxc, scf, xas
from .schema import TaskDialogSpec


class WorkflowStage(Enum):
    """Broad workflow stage used only to recommend guided actions."""

    SCF = "scf"
    POST_SCF = "post_scf"


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Guy4ASE metadata for one task with a dedicated guided editor."""

    task: str
    backend_task: str
    workflow_title: str
    workflow_description: str
    workflow_stage: WorkflowStage
    spec_builder: Callable[[bool], TaskDialogSpec]

    def dialog_spec(self, *, is_2d: bool = False) -> TaskDialogSpec:
        spec = self.spec_builder(is_2d)
        spec.primary_pages()
        return spec


_TASKS = (
    GuidedTaskDefinition(
        "scf",
        "scf",
        "Converge SCF",
        "Prepare and run a self-consistent calculation",
        WorkflowStage.SCF,
        scf.build_spec,
    ),
    GuidedTaskDefinition(
        "xas",
        "xas",
        "Calculate XAS",
        "X-ray absorption spectroscopy",
        WorkflowStage.POST_SCF,
        xas.build_spec,
    ),
    GuidedTaskDefinition(
        "arpes",
        "arpes",
        "Calculate ARPES",
        "Angle-resolved photoemission spectroscopy",
        WorkflowStage.POST_SCF,
        arpes.build_spec,
    ),
    GuidedTaskDefinition(
        "dos",
        "dos",
        "Calculate DOS",
        "Electronic density of states",
        WorkflowStage.POST_SCF,
        dos.build_spec,
    ),
    GuidedTaskDefinition(
        "bsf",
        "bsf",
        "Calculate BSF",
        "Bloch spectral function along an E–k path or on a k–k plane",
        WorkflowStage.POST_SCF,
        bsf.build_spec,
    ),
    GuidedTaskDefinition(
        "jxc",
        "jxc",
        "Calculate JXC",
        "Exchange coupling and Dzyaloshinskii–Moriya interactions",
        WorkflowStage.POST_SCF,
        jxc.build_spec,
    ),
)
_TASKS_BY_NAME = {definition.task: definition for definition in _TASKS}


def guided_task_definitions() -> tuple[GuidedTaskDefinition, ...]:
    """Return guided tasks in their workflow presentation order."""
    return _TASKS


def guided_task_definition(task: str) -> GuidedTaskDefinition:
    """Return Guy4ASE metadata for one guided task."""
    normalized = str(task).strip().lower()
    try:
        return _TASKS_BY_NAME[normalized]
    except KeyError:
        raise ValueError(
            f"No guided setup is defined for task {normalized.upper()}."
        ) from None


def task_dialog_spec(task: str, *, is_2d: bool = False) -> TaskDialogSpec:
    """Return the validated declarative dialog layout for one guided task."""
    return guided_task_definition(task).dialog_spec(is_2d=is_2d)
