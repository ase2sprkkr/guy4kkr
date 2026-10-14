"""Single Qt-free owner of Guided workflow availability and ordering."""
from __future__ import annotations

from typing import Any, Protocol

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_model import (
    ActionIcon,
    ActionStyle,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    EmptySphereUpdate,
    Load,
    LoadKind,
    RunTask,
    ScfProgress,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    WorkflowCommand,
    WorkflowPlan,
    WorkflowSection,
)
from guy4ase.gui.input_parameters.tasks import WorkflowStage, workflow_tasks


class WorkflowWorkspace(Protocol):
    """Existing read contract consumed from ``WorkspaceController``."""

    @property
    def atoms(self) -> Any: ...

    @property
    def empty_spheres(self) -> Any: ...

    def structure_kind(self) -> str | None: ...

    def can_build_2d(self) -> bool: ...

    def scf_status(self) -> str | None: ...

    def is_scf_converged(self) -> bool: ...

    def has_vacuum_sites(self) -> bool: ...

    def structure_change_requires_scf_restart(self) -> bool: ...


_SCF_PROGRESS_BY_STATUS = {
    "ITR": ScfProgress.ITERATING,
    "ITR-BULK": ScfProgress.BULK,
    "ITR-L-BULK": ScfProgress.LEFT_BULK,
    "ITR-R-BULK": ScfProgress.RIGHT_BULK,
    "ITR-I-ZONE": ScfProgress.INTERACTION_ZONE,
}

_SCF_PROGRESS_LABELS = {
    ScfProgress.NOT_STARTED: "not converged",
    ScfProgress.ITERATING: "iterating SCF",
    ScfProgress.BULK: "converging bulk",
    ScfProgress.LEFT_BULK: "converging left bulk",
    ScfProgress.RIGHT_BULK: "converging right bulk",
    ScfProgress.INTERACTION_ZONE: "converging interaction zone",
    ScfProgress.CONVERGED: "CONVERGED",
    ScfProgress.UNKNOWN: "unknown",
}


def classify_scf_progress(status: str | None, *, converged: bool) -> ScfProgress:
    """Normalize SPR-KKR SCF state once for Guided presentation policy."""
    if converged:
        return ScfProgress.CONVERGED
    if status is None:
        return ScfProgress.NOT_STARTED
    normalized = str(status).strip().upper()
    if not normalized or normalized == "START":
        return ScfProgress.NOT_STARTED
    return _SCF_PROGRESS_BY_STATUS.get(normalized, ScfProgress.UNKNOWN)


def _action(
    command: WorkflowCommand,
    title: str,
    description: str,
    style: ActionStyle,
    icon: ActionIcon | None = None,
) -> AvailableAction:
    return AvailableAction(command, title, description, style, icon)


class WorkflowPlanner:
    """Build the complete ordered Guided-workflow presentation plan."""

    def initial_plan(self, recent: RecentLaunch | None = None) -> WorkflowPlan:
        create = AvailableActionGroup(
            WorkflowSection.CREATE,
            "Create structure",
            (
                _action(
                    CreateStructure(CreateStructureKind.THREE_D),
                    "Create a 3D Structure",
                    "Build a periodic bulk crystal",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.PROTOTYPE),
                    "Create Structure from Prototype Database",
                    "Start from a crystallographic structure prototype",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.SURFACE),
                    "Create a 2D Surface",
                    "Build a surface with vacuum on one side",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.TWO_D),
                    "Create a 2D Structure",
                    "Build an interface or transitional layer",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
            ),
        )
        load_actions = [
            _action(
                Load(LoadKind.ONLINE_STRUCTURE),
                "Download Structure from Online Database",
                "Search an online crystallographic database",
                ActionStyle.LOAD,
                ActionIcon.DOWNLOAD,
            ),
            _action(
                Load(LoadKind.STRUCTURE),
                "Load a Structure",
                "Open a supported atomic structure file",
                ActionStyle.LOAD,
                ActionIcon.OPEN,
            ),
            _action(
                Load(LoadKind.OUTPUT),
                "Load SPR-KKR Output",
                "Add a completed calculation to the result history",
                ActionStyle.LOAD,
                ActionIcon.FILE,
            ),
        ]
        if recent is not None:
            load_actions.append(
                _action(
                    ContinueRecent(recent),
                    recent.title,
                    "Continue with the most recently used structure or output",
                    ActionStyle.LOAD,
                    ActionIcon.OPEN,
                )
            )
        return WorkflowPlan(
            "Start by creating a new atomic structure or loading an existing one.",
            (
                create,
                AvailableActionGroup(
                    WorkflowSection.LOAD,
                    "Load structure",
                    tuple(load_actions),
                ),
            ),
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

        progress = classify_scf_progress(
            workspace.scf_status(),
            converged=workspace.is_scf_converged(),
        )
        converged = progress is ScfProgress.CONVERGED
        groups: list[AvailableActionGroup] = []
        calculate: list[AvailableAction] = []

        if not converged and not workspace.structure_change_requires_scf_restart():
            if workspace.empty_spheres is not None:
                calculate.append(
                    _action(
                        UpdateEmptySpheres(EmptySphereUpdate.RECALCULATE),
                        "Recalculate Empty Spheres",
                        "Find empty spheres explicitly before the SCF calculation",
                        ActionStyle.STRUCTURE,
                        ActionIcon.EMPTY_SPHERES,
                    )
                )
            elif not workspace.has_vacuum_sites():
                calculate.append(
                    _action(
                        UpdateEmptySpheres(EmptySphereUpdate.ADD),
                        "Add Empty Spheres",
                        "Find empty spheres explicitly before the SCF calculation",
                        ActionStyle.STRUCTURE,
                        ActionIcon.EMPTY_SPHERES,
                    )
                )

        stage = WorkflowStage.POST_SCF if converged else WorkflowStage.SCF
        for definition in workflow_tasks(stage):
            title = definition.workflow.label
            description = definition.workflow.description
            if definition.backend_task == "scf":
                if progress.can_continue:
                    title = "Continue SCF"
                    description = (
                        f"Resume from {_SCF_PROGRESS_LABELS[progress]} "
                        "using the current potential"
                    )
                elif workspace.structure_kind() == "2d":
                    description = "Converge bulk region(s), then the interaction zone"
            calculate.append(
                _action(
                    RunTask(definition.backend_task),
                    title,
                    description,
                    ActionStyle.CALCULATION,
                    ActionIcon.RUN,
                )
            )

        if calculate:
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CALCULATE,
                    "Calculate",
                    tuple(calculate),
                )
            )

        groups.append(
            AvailableActionGroup(
                WorkflowSection.VIEW,
                "View",
                (
                    _action(
                        VisualizeStructure(),
                        "Visualize Structure",
                        "Open the current structure in the configured ASE viewer",
                        ActionStyle.NEUTRAL,
                        ActionIcon.VIEW,
                    ),
                ),
            )
        )

        if workspace.can_build_2d():
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CREATE,
                    "Create derived structure",
                    (
                        _action(
                            Build2D(Build2DKind.SURFACE),
                            "Create a 2D Surface",
                            "Derive a surface from the current 3D structure",
                            ActionStyle.STRUCTURE,
                            ActionIcon.FILE,
                        ),
                        _action(
                            Build2D(Build2DKind.STRUCTURE),
                            "Create a 2D Structure",
                            "Derive an interface or transitional layer",
                            ActionStyle.STRUCTURE,
                            ActionIcon.FILE,
                        ),
                    ),
                )
            )

        other: list[AvailableAction] = []
        if progress is not ScfProgress.NOT_STARTED:
            other.append(
                _action(
                    UseForNewCalculation(),
                    "Use for New Calculation",
                    "Keep the current potential as starting density for a new SCF sequence",
                    ActionStyle.DESTRUCTIVE,
                    ActionIcon.NEW_CALCULATION,
                )
            )
        other.append(
            _action(
                StartOver(),
                "Start Over",
                "Choose or load a different structure",
                ActionStyle.DESTRUCTIVE,
                ActionIcon.RESET,
            )
        )
        groups.append(
            AvailableActionGroup(
                WorkflowSection.OTHER,
                "And now something completely different...",
                tuple(other),
            )
        )

        formula = atoms.get_chemical_formula()
        return WorkflowPlan(
            (
                f"Current structure: {formula}  •  "
                f"SCF status: {_SCF_PROGRESS_LABELS[progress]}"
            ),
            tuple(groups),
        )
