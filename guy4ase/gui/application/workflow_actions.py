"""Qt-free workflow action policy for the guided workflow view."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal


EmptySpheresAction = Literal["add", "recalculate"]


class WorkflowAction(Enum):
    """Semantic actions that may be offered by the guided workflow."""

    CREATE_3D = auto()
    CREATE_FROM_DATABASE = auto()
    DOWNLOAD_STRUCTURE = auto()
    CREATE_2D_SURFACE = auto()
    CREATE_2D_STRUCTURE = auto()
    LOAD_STRUCTURE = auto()
    LOAD_OUTPUT = auto()
    VISUALIZE_STRUCTURE = auto()
    ADD_EMPTY_SPHERES = auto()
    RECALCULATE_EMPTY_SPHERES = auto()
    RUN_SCF = auto()
    CONTINUE_SCF = auto()
    USE_FOR_NEW_CALCULATION = auto()
    BUILD_2D_SURFACE = auto()
    BUILD_2D_STRUCTURE = auto()
    START_OVER = auto()


@dataclass(frozen=True)
class WorkflowState:
    """Facts needed to decide non-task workflow actions.

    Task discovery and task presentation deliberately do not live here. They are
    owned by the task registry and can be composed with this policy later.
    """

    has_structure: bool
    scf_status: str | None = None
    scf_converged: bool = False
    can_run_scf: bool = False
    can_build_2d: bool = False
    empty_spheres_action: EmptySpheresAction | None = None
    structure_change_requires_scf_restart: bool = False


_INITIAL_ACTIONS = (
    WorkflowAction.CREATE_3D,
    WorkflowAction.CREATE_FROM_DATABASE,
    WorkflowAction.DOWNLOAD_STRUCTURE,
    WorkflowAction.CREATE_2D_SURFACE,
    WorkflowAction.CREATE_2D_STRUCTURE,
    WorkflowAction.LOAD_STRUCTURE,
    WorkflowAction.LOAD_OUTPUT,
)

_ITERATING_SCF_STAGES = frozenset(
    {
        "ITR",
        "ITR-BULK",
        "ITR-L-BULK",
        "ITR-R-BULK",
        "ITR-I-ZONE",
    }
)


class WorkflowActions:
    """Determine semantic non-task actions for a workflow state."""

    @staticmethod
    def for_state(state: WorkflowState) -> tuple[WorkflowAction, ...]:
        if not state.has_structure:
            return _INITIAL_ACTIONS

        actions: list[WorkflowAction] = [WorkflowAction.VISUALIZE_STRUCTURE]

        if not state.scf_converged:
            if not state.structure_change_requires_scf_restart:
                if state.empty_spheres_action == "add":
                    actions.append(WorkflowAction.ADD_EMPTY_SPHERES)
                elif state.empty_spheres_action == "recalculate":
                    actions.append(WorkflowAction.RECALCULATE_EMPTY_SPHERES)

            if state.can_run_scf:
                actions.append(
                    WorkflowAction.CONTINUE_SCF
                    if state.scf_status in _ITERATING_SCF_STAGES
                    else WorkflowAction.RUN_SCF
                )

        if state.scf_converged or (
            state.scf_status is not None and state.scf_status != "START"
        ):
            actions.append(WorkflowAction.USE_FOR_NEW_CALCULATION)

        if state.can_build_2d:
            actions.extend(
                (
                    WorkflowAction.BUILD_2D_SURFACE,
                    WorkflowAction.BUILD_2D_STRUCTURE,
                )
            )

        actions.append(WorkflowAction.START_OVER)
        return tuple(actions)
