"""Qt-independent Guided-workflow presentation model."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union

from guy4ase.gui.application.recent_presentation import RecentLaunch
from guy4ase.gui.input_parameters.tasks import GuidedTaskDefinition


class ScfProgress(Enum):
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
            ScfProgress.ITERATING,
            ScfProgress.BULK,
            ScfProgress.LEFT_BULK,
            ScfProgress.RIGHT_BULK,
            ScfProgress.INTERACTION_ZONE,
        }


class CreateStructureKind(Enum):
    THREE_D = auto()
    PROTOTYPE = auto()
    SURFACE = auto()
    TWO_D = auto()


class Build2DKind(Enum):
    SURFACE = auto()
    STRUCTURE = auto()


class LoadKind(Enum):
    ONLINE_STRUCTURE = auto()
    STRUCTURE = auto()
    OUTPUT = auto()


class WorkflowSection(Enum):
    CALCULATE = auto()
    VIEW = auto()
    CREATE = auto()
    LOAD = auto()
    OTHER = auto()


class ActionStyle(Enum):
    CALCULATION = auto()
    STRUCTURE = auto()
    LOAD = auto()
    NEUTRAL = auto()
    DESTRUCTIVE = auto()


class ActionIcon(Enum):
    RUN = auto()
    EMPTY_SPHERES = auto()
    OPEN = auto()
    DOWNLOAD = auto()
    FILE = auto()
    RESULT = auto()
    VIEW = auto()
    CONTINUE = auto()
    NEW_CALCULATION = auto()
    RESET = auto()


@dataclass(frozen=True)
class RunTask:
    task: GuidedTaskDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.task, GuidedTaskDefinition):
            raise TypeError("RunTask requires a GuidedTaskDefinition.")


@dataclass(frozen=True)
class UpdateEmptySpheres:
    pass


@dataclass(frozen=True)
class CreateStructure:
    kind: CreateStructureKind


@dataclass(frozen=True)
class Build2D:
    kind: Build2DKind


@dataclass(frozen=True)
class Load:
    kind: LoadKind


@dataclass(frozen=True)
class ContinueRecent:
    launch: RecentLaunch


@dataclass(frozen=True)
class VisualizeStructure:
    pass


@dataclass(frozen=True)
class UseForNewCalculation:
    pass


@dataclass(frozen=True)
class StartOver:
    pass


WorkflowCommand = Union[
    RunTask,
    UpdateEmptySpheres,
    CreateStructure,
    Build2D,
    Load,
    ContinueRecent,
    VisualizeStructure,
    UseForNewCalculation,
    StartOver,
]


@dataclass(frozen=True)
class AvailableAction:
    command: WorkflowCommand
    title: str
    description: str
    style: ActionStyle
    icon: ActionIcon | None = None


@dataclass(frozen=True)
class AvailableActionGroup:
    section: WorkflowSection
    title: str
    actions: tuple[AvailableAction, ...]

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("Workflow action groups must not be empty.")


@dataclass(frozen=True)
class WorkflowPlan:
    subtitle: str
    groups: tuple[AvailableActionGroup, ...]

    def __post_init__(self) -> None:
        sections = tuple(group.section for group in self.groups)
        if len(set(sections)) != len(sections):
            raise ValueError("Workflow plan must contain each section at most once.")

    def group(self, section: WorkflowSection) -> AvailableActionGroup | None:
        for group in self.groups:
            if group.section is section:
                return group
        return None
