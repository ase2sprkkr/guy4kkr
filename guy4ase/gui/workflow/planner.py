"""Single Qt-free owner of Guided workflow availability and ordering."""
from __future__ import annotations

from enum import Enum, auto
from typing import Any, Protocol

from guy4ase.gui.application.workspace_actions import EmptySpheresAction
from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    guided_task_definition,
    workflow_tasks,
)
from guy4ase.gui.presentation import ActionCategory, RecentLaunch
from guy4ase.gui.workflow.model import (
    ActionIcon,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    WorkflowCommand,
    WorkflowPlan,
    WorkflowSection,
)
from guy4ase.physics.lattice import StructureKind


class WorkflowWorkspace(Protocol):
    """Read contract consumed from ``WorkspaceController``."""

    @property
    def atoms(self) -> Any: ...

    def structure_kind(self) -> StructureKind | None: ...

    def can_build_2d(self) -> bool: ...

    def scf_status(self) -> str | None: ...

    def is_scf_converged(self) -> bool: ...

    def empty_spheres_action(self) -> EmptySpheresAction | None: ...

    def structure_change_requires_scf_restart(self) -> bool: ...


class _ScfProgress(Enum):
    NOT_STARTED = auto()
    ITERATING = auto()
    BULK = auto()
    LEFT_BULK = auto()
    RIGHT_BULK = auto()
    INTERACTION_ZONE = auto()
    CONVERGED = auto()
    UNKNOWN = auto()

    @property
    def can_continue(self) -> bool:
        return self in {
            _ScfProgress.ITERATING,
            _ScfProgress.BULK,
            _ScfProgress.LEFT_BULK,
            _ScfProgress.RIGHT_BULK,
            _ScfProgress.INTERACTION_ZONE,
        }


_SCF_PROGRESS_BY_STATUS = {
    "ITR": _ScfProgress.ITERATING,
    "ITR-BULK": _ScfProgress.BULK,
    "ITR-L-BULK": _ScfProgress.LEFT_BULK,
    "ITR-R-BULK": _ScfProgress.RIGHT_BULK,
    "ITR-I-ZONE": _ScfProgress.INTERACTION_ZONE,
}

_SCF_PROGRESS_LABELS = {
    _ScfProgress.NOT_STARTED: "not converged",
    _ScfProgress.ITERATING: "iterating SCF",
    _ScfProgress.BULK: "converging bulk",
    _ScfProgress.LEFT_BULK: "converging left bulk",
    _ScfProgress.RIGHT_BULK: "converging right bulk",
    _ScfProgress.INTERACTION_ZONE: "converging interaction zone",
    _ScfProgress.CONVERGED: "CONVERGED",
}

_SCF_TASK = guided_task_definition("scf")


def _classify_scf_progress(status: str | None, *, converged: bool) -> _ScfProgress:
    if converged:
        return _ScfProgress.CONVERGED
    if status is None:
        return _ScfProgress.NOT_STARTED
    normalized = str(status).strip().upper()
    if not normalized or normalized == "START":
        return _ScfProgress.NOT_STARTED
    return _SCF_PROGRESS_BY_STATUS.get(normalized, _ScfProgress.UNKNOWN)


def _scf_status_text(progress: _ScfProgress, status: str | None) -> str:
    if progress is _ScfProgress.UNKNOWN:
        normalized = "" if status is None else str(status).strip().upper()
        return normalized or "unknown"
    return _SCF_PROGRESS_LABELS[progress]


def _action(
    command: WorkflowCommand,
    title: str,
    description: str,
    category: ActionCategory,
    icon: ActionIcon,
) -> AvailableAction:
    return AvailableAction(command, title, description, category, icon)


class WorkflowPlanner:
    """Build the complete ordered Guided workflow presentation plan."""

    def initial_plan(self, recent: RecentLaunch | None = None) -> WorkflowPlan:
        create = AvailableActionGroup(
            WorkflowSection.CREATE,
            "Create structure",
            (
                _action(CreateStructure(CreateStructureKind.THREE_D), "Create a 3D Structure", "Build a periodic bulk crystal", "structure", ActionIcon.FILE),
                _action(CreateStructure(CreateStructureKind.PROTOTYPE), "Create Structure from Prototype Database", "Start from a crystallographic structure prototype", "structure", ActionIcon.FILE),
                _action(CreateStructure(CreateStructureKind.SURFACE), "Create a 2D Surface", "Build a surface with vacuum on one side", "structure", ActionIcon.FILE),
                _action(CreateStructure(CreateStructureKind.TWO_D), "Create a 2D Structure", "Build an interface or transitional layer", "structure", ActionIcon.FILE),
            ),
        )
        load_actions = [
            _action(Load(LoadKind.ONLINE_STRUCTURE), "Download Structure from Online Database", "Search an online crystallographic database", "load", ActionIcon.DOWNLOAD),
            _action(Load(LoadKind.STRUCTURE), "Load a Structure", "Open a supported atomic structure file", "load", ActionIcon.OPEN),
            _action(Load(LoadKind.OUTPUT), "Load SPR-KKR Output", "Add a completed calculation to the result history", "load", ActionIcon.RESULT),
        ]
        if recent is not None:
            load_actions.append(_action(ContinueRecent(recent), recent.title, "", "load", ActionIcon.CONTINUE))
        return WorkflowPlan(
            "Start by creating a new atomic structure or loading an existing one.",
            (create, AvailableActionGroup(WorkflowSection.LOAD, "Load structure", tuple(load_actions))),
        )

    def for_workspace(
        self,
        workspace: WorkflowWorkspace,
        *,
        recent: RecentLaunch | None = None,
    ) -> WorkflowPlan:
        atoms = workspace.atoms
        if atoms is None:
            return self.initial_plan(recent)

        status = workspace.scf_status()
        progress = _classify_scf_progress(status, converged=workspace.is_scf_converged())
        converged = progress is _ScfProgress.CONVERGED
        groups: list[AvailableActionGroup] = []
        calculate: list[AvailableAction] = []

        if not converged and not workspace.structure_change_requires_scf_restart():
            empty_spheres = workspace.empty_spheres_action()
            if empty_spheres is not None:
                calculate.append(
                    _action(
                        UpdateEmptySpheres(),
                        "Recalculate Empty Spheres" if empty_spheres is EmptySpheresAction.RECALCULATE else "Add Empty Spheres",
                        "Find empty spheres explicitly before the SCF calculation",
                        "structure",
                        ActionIcon.EMPTY_SPHERES,
                    )
                )

        stage = WorkflowStage.POST_SCF if converged else WorkflowStage.SCF
        for definition in workflow_tasks(stage):
            title = definition.workflow.label
            description = definition.workflow.description
            if definition is _SCF_TASK:
                if progress.can_continue:
                    title = "Continue SCF"
                    description = f"Resume from {_SCF_PROGRESS_LABELS[progress]} using the current potential"
                elif workspace.structure_kind() == "2d":
                    description = "Converge bulk region(s), then the interaction zone"
            calculate.append(_action(RunTask(definition), title, description, "calculation", ActionIcon.RUN))

        if calculate:
            groups.append(AvailableActionGroup(WorkflowSection.CALCULATE, "Calculate", tuple(calculate)))

        groups.append(
            AvailableActionGroup(
                WorkflowSection.VIEW,
                "View",
                (_action(VisualizeStructure(), "Visualize Structure", "Open the current structure in the configured ASE viewer", "neutral", ActionIcon.VIEW),),
            )
        )

        if workspace.can_build_2d():
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CREATE,
                    "Create derived structure",
                    (
                        _action(Build2D(Build2DKind.SURFACE), "Create a 2D Surface", "Derive a surface from the current 3D structure", "structure", ActionIcon.FILE),
                        _action(Build2D(Build2DKind.STRUCTURE), "Create a 2D Structure", "Derive an interface or transitional layer", "structure", ActionIcon.FILE),
                    ),
                )
            )

        other: list[AvailableAction] = []
        if progress is not _ScfProgress.NOT_STARTED:
            other.append(_action(UseForNewCalculation(), "Use for New Calculation", "Keep the current potential as starting density for a new SCF sequence", "destructive", ActionIcon.NEW_CALCULATION))
        other.append(_action(StartOver(), "Start Over", "Choose or load a different structure", "destructive", ActionIcon.RESET))
        groups.append(AvailableActionGroup(WorkflowSection.OTHER, "And now something completely different...", tuple(other)))

        formula = atoms.get_chemical_formula()
        return WorkflowPlan(
            f"Current structure: {formula}  •  SCF status: {_scf_status_text(progress, status)}",
            tuple(groups),
        )
