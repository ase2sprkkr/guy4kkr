"""Qt-free presentation model for the Guided workflow window.

The workflow planner owns which actions are offered, their grouping and their
ordering. Qt views consume the resulting :class:`WorkflowPlan` as a rendering
contract and do not reconstruct workflow policy themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol, Union

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.application.workflow_facts import EmptySpheresAction, ScfProgress


class WorkflowCommandKind(Enum):
    """Major semantic family of a Guided workflow command."""

    RUN_TASK = auto()
    UPDATE_EMPTY_SPHERES = auto()
    CREATE_STRUCTURE = auto()
    BUILD_2D = auto()
    LOAD = auto()
    VISUALIZE = auto()
    USE_FOR_NEW_CALCULATION = auto()
    START_OVER = auto()


class CreateStructureAction(Enum):
    """Ways to create a structure before one is active."""

    THREE_D = auto()
    PROTOTYPE = auto()
    SURFACE = auto()
    TWO_D = auto()


class Build2DAction(Enum):
    """2D structures derivable from an active 3D structure."""

    SURFACE = auto()
    STRUCTURE = auto()


class LoadAction(Enum):
    """Static sources which can populate workflow state or result history."""

    ONLINE_STRUCTURE = auto()
    STRUCTURE = auto()
    OUTPUT = auto()


class WorkflowSection(Enum):
    """Semantic section in which an action is presented."""

    CALCULATE = auto()
    VIEW = auto()
    CREATE = auto()
    LOAD = auto()
    OTHER = auto()


class ActionStyle(Enum):
    """Semantic visual role; the Qt view maps this role to concrete styling."""

    CALCULATION = auto()
    STRUCTURE = auto()
    LOAD = auto()
    NEUTRAL = auto()
    DESTRUCTIVE = auto()


class ActionIcon(Enum):
    """Qt-independent icon roles used by the Guided workflow."""

    RUN = auto()
    EMPTY_SPHERES = auto()
    OPEN = auto()
    DOWNLOAD = auto()
    FILE = auto()
    VIEW = auto()
    NEW_CALCULATION = auto()
    RESET = auto()


CommandArgument = Union[str, Enum, RecentLaunch, None]


@dataclass(frozen=True)
class WorkflowCommand:
    """Semantic command dispatched when a workflow action is activated.

    ``kind`` describes the operation family. ``minor`` identifies the concrete
    operation within that family. Backend task identifiers intentionally remain
    strings; other command families use semantic enums or immutable value objects.
    """

    kind: WorkflowCommandKind
    minor: CommandArgument = None


@dataclass(frozen=True)
class AvailableAction:
    """One fully described action ready for presentation by a view."""

    command: WorkflowCommand
    title: str
    description: str
    style: ActionStyle
    icon: ActionIcon | None = None


@dataclass(frozen=True)
class AvailableActionGroup:
    """Ordered actions belonging to one semantic Guided-workflow section."""

    section: WorkflowSection
    title: str
    actions: tuple[AvailableAction, ...]

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("Workflow action groups must not be empty.")


@dataclass(frozen=True)
class WorkflowPlan:
    """Complete ordered presentation plan for the Guided workflow view."""

    subtitle: str
    groups: tuple[AvailableActionGroup, ...]

    def group(self, section: WorkflowSection) -> AvailableActionGroup | None:
        """Return the group for *section*, if the current plan contains one."""
        for group in self.groups:
            if group.section is section:
                return group
        return None


class WorkflowWorkspace(Protocol):
    """Narrow read contract consumed by Guided workflow presentation policy."""

    @property
    def atoms(self) -> Any: ...

    def scf_progress(self) -> ScfProgress: ...

    def can_build_2d(self) -> bool: ...

    def empty_spheres_action(self) -> EmptySpheresAction | None: ...

    def structure_change_requires_scf_restart(self) -> bool: ...


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


def _action(
    kind: WorkflowCommandKind,
    minor: CommandArgument,
    title: str,
    description: str,
    style: ActionStyle,
    icon: ActionIcon | None = None,
) -> AvailableAction:
    return AvailableAction(
        command=WorkflowCommand(kind, minor),
        title=title,
        description=description,
        style=style,
        icon=icon,
    )


class WorkflowPlanner:
    """Build ordered Guided-workflow presentation plans.

    Task actions are deliberately not catalogued here. Once the central Guided
    task registry lands on the integration branch, its definitions are composed
    into the Calculate group without introducing a parallel task list.
    """

    @staticmethod
    def initial_plan(recent: RecentLaunch | None = None) -> WorkflowPlan:
        """Return the plan shown before any structure has been selected."""
        create = AvailableActionGroup(
            section=WorkflowSection.CREATE,
            title="Create structure",
            actions=(
                _action(
                    WorkflowCommandKind.CREATE_STRUCTURE,
                    CreateStructureAction.THREE_D,
                    "Create a 3D Structure",
                    "Build a periodic bulk crystal",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    WorkflowCommandKind.CREATE_STRUCTURE,
                    CreateStructureAction.PROTOTYPE,
                    "Create Structure from Prototype Database",
                    "Start from a crystallographic structure prototype",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    WorkflowCommandKind.CREATE_STRUCTURE,
                    CreateStructureAction.SURFACE,
                    "Create a 2D Surface",
                    "Build a surface with vacuum on one side",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
                _action(
                    WorkflowCommandKind.CREATE_STRUCTURE,
                    CreateStructureAction.TWO_D,
                    "Create a 2D Structure",
                    "Build an interface or transitional layer",
                    ActionStyle.STRUCTURE,
                    ActionIcon.FILE,
                ),
            ),
        )
        load_actions = [
            _action(
                WorkflowCommandKind.LOAD,
                LoadAction.ONLINE_STRUCTURE,
                "Download Structure from Online Database",
                "Search an online crystallographic database",
                ActionStyle.LOAD,
                ActionIcon.DOWNLOAD,
            ),
            _action(
                WorkflowCommandKind.LOAD,
                LoadAction.STRUCTURE,
                "Load a Structure",
                "Open a supported atomic structure file",
                ActionStyle.LOAD,
                ActionIcon.OPEN,
            ),
            _action(
                WorkflowCommandKind.LOAD,
                LoadAction.OUTPUT,
                "Load SPR-KKR Output",
                "Add a completed calculation to the result history",
                ActionStyle.LOAD,
                ActionIcon.FILE,
            ),
        ]
        if recent is not None:
            load_actions.append(
                _action(
                    WorkflowCommandKind.LOAD,
                    recent,
                    recent.title,
                    "Continue with the most recently used structure or output",
                    ActionStyle.LOAD,
                    ActionIcon.OPEN,
                )
            )
        load = AvailableActionGroup(
            section=WorkflowSection.LOAD,
            title="Load structure",
            actions=tuple(load_actions),
        )
        return WorkflowPlan(
            subtitle=(
                "Start by creating a new atomic structure or loading an existing one."
            ),
            groups=(create, load),
        )

    @classmethod
    def for_workspace(
        cls,
        workspace: WorkflowWorkspace,
        *,
        recent: RecentLaunch | None = None,
    ) -> WorkflowPlan:
        """Build the non-task portion of the plan for the active workspace."""
        atoms = workspace.atoms
        if atoms is None:
            return cls.initial_plan(recent)

        progress = workspace.scf_progress()
        groups: list[AvailableActionGroup] = []

        calculate_actions: list[AvailableAction] = []
        if (
            progress is not ScfProgress.CONVERGED
            and not workspace.structure_change_requires_scf_restart()
        ):
            empty_spheres = workspace.empty_spheres_action()
            if empty_spheres is not None:
                calculate_actions.append(
                    _action(
                        WorkflowCommandKind.UPDATE_EMPTY_SPHERES,
                        empty_spheres,
                        (
                            "Recalculate Empty Spheres"
                            if empty_spheres is EmptySpheresAction.RECALCULATE
                            else "Add Empty Spheres"
                        ),
                        "Find empty spheres explicitly before the SCF calculation",
                        ActionStyle.STRUCTURE,
                        ActionIcon.EMPTY_SPHERES,
                    )
                )
        if calculate_actions:
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CALCULATE,
                    "Calculate",
                    tuple(calculate_actions),
                )
            )

        groups.append(
            AvailableActionGroup(
                WorkflowSection.VIEW,
                "View",
                (
                    _action(
                        WorkflowCommandKind.VISUALIZE,
                        None,
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
                    "Create structure",
                    (
                        _action(
                            WorkflowCommandKind.BUILD_2D,
                            Build2DAction.SURFACE,
                            "Create a 2D Surface",
                            "Derive a surface from the current 3D structure",
                            ActionStyle.STRUCTURE,
                            ActionIcon.FILE,
                        ),
                        _action(
                            WorkflowCommandKind.BUILD_2D,
                            Build2DAction.STRUCTURE,
                            "Create a 2D Structure",
                            "Derive an interface or transitional layer",
                            ActionStyle.STRUCTURE,
                            ActionIcon.FILE,
                        ),
                    ),
                )
            )

        other_actions: list[AvailableAction] = []
        if progress is not ScfProgress.NOT_STARTED:
            other_actions.append(
                _action(
                    WorkflowCommandKind.USE_FOR_NEW_CALCULATION,
                    None,
                    "Use for New Calculation",
                    "Keep the current potential as starting density for a new SCF sequence",
                    ActionStyle.DESTRUCTIVE,
                    ActionIcon.NEW_CALCULATION,
                )
            )
        other_actions.append(
            _action(
                WorkflowCommandKind.START_OVER,
                None,
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
                tuple(other_actions),
            )
        )

        formula = atoms.get_chemical_formula()
        return WorkflowPlan(
            subtitle=(
                f"Current structure: {formula}  •  "
                f"SCF status: {_SCF_PROGRESS_LABELS[progress]}"
            ),
            groups=tuple(groups),
        )
