"""Single ownership of Guy4ASE guided-task metadata."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .specs import arpes, bsf, dos, jxc, scf, xas
from .specs.schema import TaskDialogSpec


SpecBuilder = Callable[[bool], TaskDialogSpec]


@dataclass(frozen=True)
class WorkflowTaskPresentation:
    """Presentation and recommendation metadata for one Guided workflow task."""

    label: str
    description: str
    after_converged_scf: bool = False


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Guy4ASE support for one backend task.

    Backend task existence and execution semantics remain owned by ASE2SPRKKR;
    this descriptor only states that Guy4ASE has a Guided editor and how that
    task is presented in the Guided workflow.
    """

    task: str
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
            scf.build_spec,
            WorkflowTaskPresentation(
                "Converge SCF",
                "Prepare and run a self-consistent calculation",
            ),
        ),
        GuidedTaskDefinition(
            "xas",
            xas.build_spec,
            WorkflowTaskPresentation(
                "Calculate XAS",
                "X-ray absorption spectroscopy",
                after_converged_scf=True,
            ),
        ),
        GuidedTaskDefinition(
            "arpes",
            arpes.build_spec,
            WorkflowTaskPresentation(
                "Calculate ARPES",
                "Angle-resolved photoemission spectroscopy",
                after_converged_scf=True,
            ),
        ),
        GuidedTaskDefinition(
            "dos",
            dos.build_spec,
            WorkflowTaskPresentation(
                "Calculate DOS",
                "Electronic density of states",
                after_converged_scf=True,
            ),
        ),
        GuidedTaskDefinition(
            "bsf",
            bsf.build_spec,
            WorkflowTaskPresentation(
                "Calculate BSF",
                "Bloch spectral function along an E–k path or on a k–k plane",
                after_converged_scf=True,
            ),
        ),
        GuidedTaskDefinition(
            "jxc",
            jxc.build_spec,
            WorkflowTaskPresentation(
                "Calculate JXC",
                "Exchange coupling and Dzyaloshinskii–Moriya interactions",
                after_converged_scf=True,
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
