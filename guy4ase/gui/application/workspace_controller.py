"""Semantic document transitions over the shared GUI workspace."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Any, NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState

_KEEP_DIRECTORY = object()
_RESULT_HISTORY_LIMIT = 10


def _result_is_scf(result: Any) -> bool:
    """Return whether a live calculation result belongs to an SCF task."""
    try:
        return str(result.task_name).strip().lower() == "scf"
    except (AttributeError, TypeError, ValueError):
        return False


class Generation(NamedTuple):
    """Workspace revision split into calculation epoch and local revision."""

    major: int = 0
    minor: int = 0

    def next_major(self) -> Generation:
        return Generation(self.major + 1, 0)

    def next_minor(self) -> Generation:
        return Generation(self.major, self.minor + 1)

    def same_major(self, other: Generation) -> bool:
        return self.major == other.major

    def __add__(self, value: int) -> Generation:
        if not isinstance(value, int):
            return NotImplemented
        return Generation(self.major + value, 0)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.major == other and self.minor == 0
        return tuple.__eq__(self, other)

    __hash__ = tuple.__hash__


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive document command."""

    APPLIED = auto()
    STALE = auto()


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Values captured when the user asks to start a calculation.

    ``atoms`` is deliberately borrowed, not copied, and must be treated as
    read-only by the calculation. ``input_parameters`` is an independent value
    copy so calculation preparation cannot mutate the editor document.
    """

    atoms: Any
    input_parameters: Any
    directory: str
    generation: Generation


@dataclass(frozen=True)
class ResultAdoption:
    """Artifacts and outcome of trying to adopt a calculation result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None
    input_parameters_error: Exception | None = None
    adopted: bool = True


class WorkspaceController(QObject):
    """Own semantic document transitions and its monotonic revision.

    The mutable ``WorkspaceState`` is private. Read access is exposed through
    narrow properties and semantic queries on the controller. Published
    ``atoms`` and ``input_parameters`` remain borrowed references and follow
    their existing read-only-by-contract semantics.
    """

    structureChanged = pyqtSignal(object)
    inputParametersChanged = pyqtSignal(object)
    directoryChanged = pyqtSignal(object)
    resultChanged = pyqtSignal(object)

    def __init__(
        self,
        workspace: WorkspaceState | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace or WorkspaceState()
        if self._workspace.result is not None and not self._workspace.result_history:
            self._workspace.result_history = (self._workspace.result,)
        self._generation = Generation()

    @property
    def workspace(self) -> WorkspaceController:
        """Compatibility alias for callers not yet migrated to controller reads."""
        return self

    @property
    def atoms(self) -> Any:
        """Return the current published structure; callers must not mutate it."""
        return self._workspace.atoms

    @property
    def input_parameters(self) -> Any:
        """Return current input parameters; callers must not mutate them."""
        return self._workspace.input_parameters

    @property
    def directory(self) -> str | None:
        return self._workspace.directory

    @property
    def potential_path(self) -> str | None:
        return self._workspace.potential_path

    @property
    def result(self) -> Any | None:
        return self._workspace.result

    @property
    def result_history(self) -> tuple[Any, ...]:
        return self._workspace.result_history

    @property
    def empty_spheres_added(self) -> int | None:
        return self._workspace.empty_spheres_added

    @property
    def restarted(self) -> bool:
        return self._workspace.restarted

    @property
    def generation(self) -> Generation:
        return self._generation

    def structure_kind(self):
        return self._workspace.structure_kind()

    def can_calculate(self) -> bool:
        return self._workspace.can_calculate()

    def scf_status(self) -> str | None:
        return self._workspace.scf_status()

    def is_scf_converged(self) -> bool:
        return self._workspace.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self._workspace.has_vacuum_sites()

    def empty_spheres_action(self) -> str | None:
        return self._workspace.empty_spheres_action()

    def create_calculation_request(self) -> CalculationRequest:
        """Borrow read-only Atoms and capture independent calculation inputs."""
        atoms = self.atoms
        parameters = self.input_parameters
        directory = self._workspace.directory
        if atoms is None or parameters is None or not directory:
            raise CalculationNotReady(
                "Structure, input parameters and directory are required."
            )
        return CalculationRequest(
            atoms=atoms,
            input_parameters=parameters.copy(copy_values=True),
            directory=directory,
            generation=self._generation,
        )

    def _generation_is_current(self, expected: Generation | None) -> bool:
        return expected is None or expected == self._generation

    def _calculation_generation_is_current(self, expected: Generation) -> bool:
        return expected.same_major(self._generation)

    def _changed(self) -> None:
        self._generation = self._generation.next_major()

    def _result_changed(self) -> None:
        self._generation = self._generation.next_minor()

    def _clear_result_history(self) -> bool:
        had_results = (
            self._workspace.result is not None
            or bool(self._workspace.result_history)
        )
        self._workspace.result = None
        self._workspace.result_history = ()
        return had_results

    def _remember_result(
        self, result: Any, *, replace_history: bool = False
    ) -> None:
        self._workspace.result = result
        if replace_history:
            self._workspace.result_history = (result,)
            return
        self._workspace.result_history = (
            result, *self._workspace.result_history
        )[:_RESULT_HISTORY_LIMIT]

    def _set_directory(self, directory: Any) -> bool:
        if (
            directory is _KEEP_DIRECTORY
            or directory == self._workspace.directory
        ):
            return False
        self._workspace.directory = directory
        return True

    def replace_structure(
        self,
        atoms: Any,
        *,
        potential_path: str | None = None,
        directory: Any = _KEEP_DIRECTORY,
        expected_generation: Generation | None = None,
        restarted: bool = False,
    ) -> DocumentChange:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        had_result = self._clear_result_history()
        self._workspace.atoms = atoms
        self._workspace.potential_path = potential_path
        self._workspace.empty_spheres_added = None
        self._workspace.restarted = restarted
        directory_changed = self._set_directory(directory)
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_generation: Generation,
    ) -> DocumentChange | None:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        source = self.atoms
        if source is None:
            raise ValueError("No structure is loaded.")

        atoms = edit(source.copy())
        if atoms is None:
            return None
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        had_result = self._clear_result_history()
        self._workspace.atoms = atoms
        self._workspace.restarted = True
        self._workspace.potential_path = None
        self._workspace.empty_spheres_added = None
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def replace_input_parameters(
        self,
        parameters: Any,
        *,
        directory: Any = _KEEP_DIRECTORY,
        expected_generation: Generation | None = None,
    ) -> DocumentChange:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        had_result = self._workspace.result is not None
        self._workspace.result = None
        directory_changed = self._set_directory(directory)
        self._workspace.input_parameters = parameters
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return DocumentChange.APPLIED

    def change_directory(self, directory: str | None) -> None:
        if not self._set_directory(directory):
            return
        had_result = self._workspace.result is not None
        self._workspace.result = None
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        self.directoryChanged.emit(directory)

    def adopt_external_result(
        self,
        loaded: LoadedResult,
        *,
        expected_generation: Generation,
    ) -> ResultAdoption:
        adoption = self._result_adoption(loaded)
        if not self._generation_is_current(expected_generation):
            return replace(adoption, adopted=False)

        self._remember_result(loaded.result, replace_history=True)
        self._workspace.atoms = loaded.atoms
        self._workspace.input_parameters = loaded.input_parameters
        self._workspace.potential_path = (
            str(loaded.potential_path)
            if loaded.atoms is not None
            else None
        )
        self._workspace.empty_spheres_added = None
        self._workspace.restarted = False
        directory_changed = self._set_directory(loaded.directory)
        self._changed()

        self.structureChanged.emit(loaded.atoms)
        self.inputParametersChanged.emit(loaded.input_parameters)
        if directory_changed:
            self.directoryChanged.emit(loaded.directory)
        self.resultChanged.emit(loaded.result)
        return adoption

    @staticmethod
    def _result_adoption(
        loaded: LoadedResult, *, adopted: bool = True
    ) -> ResultAdoption:
        return ResultAdoption(
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            potential_error=loaded.potential_error,
            input_parameters_error=loaded.input_parameters_error,
            adopted=adopted,
        )

    def adopt_calculation_result(
        self,
        loaded: LoadedResult,
        *,
        expected_generation: Generation,
    ) -> ResultAdoption:
        adoption = self._result_adoption(loaded)
        if not self._calculation_generation_is_current(expected_generation):
            return replace(adoption, adopted=False)

        if loaded.atoms is not None:
            self._workspace.atoms = loaded.atoms
            self._workspace.potential_path = str(loaded.potential_path)
            if _result_is_scf(loaded.result):
                self._workspace.restarted = False
        self._remember_result(loaded.result)
        self._result_changed()

        if loaded.atoms is not None:
            self.structureChanged.emit(loaded.atoms)
        self.resultChanged.emit(loaded.result)
        return adoption

    def reset(self) -> None:
        self._clear_result_history()
        self._workspace.atoms = None
        self._workspace.potential_path = None
        self._workspace.input_parameters = None
        self._workspace.empty_spheres_added = None
        self._workspace.restarted = False
        self._set_directory(None)
        self._changed()
        self.resultChanged.emit(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)

    def use_for_new_calculation(
        self, *, expected_generation: Generation | None = None
    ) -> DocumentChange:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        had_result = self._workspace.result is not None
        self._workspace.result = None
        self._workspace.restarted = True
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        return DocumentChange.APPLIED

    def update_empty_spheres(
        self,
        edit: Callable[[Any, int], tuple[Any, int, bool]],
        *,
        expected_generation: Generation,
        parameters: Mapping[str, Any] | None = None,
    ) -> DocumentChange:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        source = self.atoms
        if source is None:
            raise ValueError("No structure is loaded.")

        previous_count = self._workspace.empty_spheres_added or 0
        updated, count, structure_changed = edit(source.copy(), previous_count)
        count = int(count)
        if count < 0:
            raise ValueError("Empty-sphere count cannot be negative.")
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        result = EmptySpheresResult(found=count, parameters=parameters or {})
        self._workspace.empty_spheres_added = count
        if structure_changed:
            self._clear_result_history()
            self._workspace.atoms = updated
            self._workspace.potential_path = None
            self._workspace.restarted = True
            self._changed()
        self._remember_result(result)

        self.structureChanged.emit(updated if structure_changed else source)
        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
