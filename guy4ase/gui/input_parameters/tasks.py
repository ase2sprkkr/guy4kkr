"""Single ownership of Guy4ASE guided-task metadata."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .specs import arpes, bsf, dos, jxc, scf, xas
from .specs.schema import TaskDialogSpec


SpecBuilder = Callable[[bool], TaskDialogSpec]


class WorkflowStage(Enum):
    """Semantic stage in which a task is presented by the Guided workflow."""

    SCF = "scf"
    POST_SCF = "post-scf"


@dataclass(frozen=True)
class WorkflowTaskPresentation:
    """Presentation metadata for one Guided workflow task."""

    label: str
    description: str
    stage: WorkflowStage


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Guy4ASE support for one backend task.

    Backend task existence and execution semantics remain owned by ASE2SPRKKR;
    this descriptor only maps one Guided action to its backend task, its dialog
    layout and its Guided-workflow presentation.
    """

    task: str
    backend_task: str
    spec_builder: SpecBuilder
    workflow: WorkflowTaskPresentation

    def dialog_spec(self, *, is_2d: bool = False) -> TaskDialogSpec:
        spec = self.spec_builder(is_2d)
        spec.primary_pages()
        return spec


_GUIDED_TASKS = {
    definition.task: definition
    for definition in (
        GuidedTaskDefinition(
            "scf",
            "scf",
            scf.build_spec,
            WorkflowTaskPresentation(
                "Converge SCF",
                "Prepare and run a self-consistent calculation",
                WorkflowStage.SCF,
            ),
        ),
        GuidedTaskDefinition(
            "xas",
            "xas",
            xas.build_spec,
            WorkflowTaskPresentation(
                "Calculate XAS",
                "X-ray absorption spectroscopy",
                WorkflowStage.POST_SCF,
            ),
        ),
        GuidedTaskDefinition(
            "arpes",
            "arpes",
            arpes.build_spec,
            WorkflowTaskPresentation(
                "Calculate ARPES",
                "Angle-resolved photoemission spectroscopy",
                WorkflowStage.POST_SCF,
            ),
        ),
        GuidedTaskDefinition(
            "dos",
            "dos",
            dos.build_spec,
            WorkflowTaskPresentation(
                "Calculate DOS",
                "Electronic density of states",
                WorkflowStage.POST_SCF,
            ),
        ),
        GuidedTaskDefinition(
            "bsf",
            "bsf",
            bsf.build_spec,
            WorkflowTaskPresentation(
                "Calculate BSF",
                "Bloch spectral function along an E–k path or on a k–k plane",
                WorkflowStage.POST_SCF,
            ),
        ),
        GuidedTaskDefinition(
            "jxc",
            "jxc",
            jxc.build_spec,
            WorkflowTaskPresentation(
                "Calculate JXC",
                "Exchange coupling and Dzyaloshinskii–Moriya interactions",
                WorkflowStage.POST_SCF,
            ),
        ),
    )
}


def guided_task_definition(task: str) -> GuidedTaskDefinition:
    """Return Guy4ASE's Guided definition for *task*."""
    normalized = str(task).strip().lower()
    try:
        return _GUIDED_TASKS[normalized]
    except KeyError:
        raise ValueError(
            f"No guided setup is defined for task {normalized.upper()}."
        ) from None


def guided_task_definitions() -> tuple[GuidedTaskDefinition, ...]:
    """Return Guided tasks in workflow presentation order."""
    return tuple(_GUIDED_TASKS.values())
