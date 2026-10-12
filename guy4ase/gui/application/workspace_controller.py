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
    """Workspace revision split into calculation epoch and local revision.

    ``major`` changes when an operation invalidates calculations already in
    flight. ``minor`` changes for published workspace changes, such as adopting
    a calculation result, which must invalidate stale editor drafts but not
    sibling calculations started from the same major generation.
    """

    major: int = 0
    minor: int = 0

    def next_major(self) -> Generation:
        return Generation(self.major + 1, 0)

    def next_minor(self) -> Generation:
        return Generation(self.major, self.minor + 1)

    def same_major(self, other: Generation) -> bool:
        return self.major == other.major

    def __add__(self, value: int) -> Generation:
        """Advance the major generation; kept useful for revision assertions."""
        if not isinstance(value, int):
            return NotImplemented
        return Generation(self.major + value, 0)

    def __eq__(self, other: object) -> bool:
        # ``generation == 0`` existed in a few regression tests before the
        # generation became two-dimensional. Treat an int as major with zero
        # minor; normal production code should compare Generation values.
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

    Published ``atoms`` and ``input_parameters`` are read-only by contract.
    Structure edits use copy-on-write and publish a new object only after the
    edit succeeds. Full generations reject stale editor/document transactions;
    calculation results only require the major generation to stay current so
    parallel runs from the same calculation epoch can all be adopted.
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
        self.workspace = workspace or WorkspaceState()
        if self.workspace.result is not None and not self.workspace.result_history:
            self.workspace.result_history = (self.workspace.result,)
        self._generation = Generation()

    @property
    def atoms(self) -> Any:
        """Return the current published structure; callers must not mutate it."""
        return self.workspace.atoms

    @property
    def input_parameters(self) -> Any:
        """Return current input parameters; callers must not mutate them."""
        return self.workspace.input_parameters

    @property
    def generation(self) -> Generation:
        return self._generation

    def create_calculation_request(self) -> CalculationRequest:
        """Borrow read-only Atoms and capture independent calculation inputs."""
        atoms = self.atoms
        parameters = self.input_parameters
        directory = self.workspace.directory
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
        """Publish a change which invalidates calculations already in flight."""
        self._generation = self._generation.next_major()

    def _result_changed(self) -> None:
        """Publish a result without invalidating sibling calculations."""
        self._generation = self._generation.next_minor()

    def _clear_result_history(self) -> bool:
        """Clear the current result and browsing history."""
        had_results = (
            self.workspace.result is not None
            or bool(self.workspace.result_history)
        )
        self.workspace.result = None
        self.workspace.result_history = ()
        return had_results

    def _remember_result(
        self, result: Any, *, replace_history: bool = False
    ) -> None:
        """Make a result current and remember it for later browsing."""
        self.workspace.result = result
        if replace_history:
            self.workspace.result_history = (result,)
            return
        self.workspace.result_history = (
            result, *self.workspace.result_history
        )[:_RESULT_HISTORY_LIMIT]

    def _set_directory(self, directory: Any) -> bool:
        """Set a requested directory and report whether it actually changed."""
        if (
            directory is _KEEP_DIRECTORY
            or directory == self.workspace.directory
        ):
            return False
        self.workspace.directory = directory
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
        self.workspace.atoms = atoms
        self.workspace.potential_path = potential_path
        self.workspace.empty_spheres_added = None
        self.workspace.restarted = restarted
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
        """Apply an edit to a detached copy and atomically publish the result.

        ``edit`` may run a long-lived dialog. Therefore the generation is
        checked both before making the candidate and again after the callback
        returns. Returning ``None`` means the edit was cancelled and leaves the
        workspace untouched.
        """
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
        self.workspace.atoms = atoms
        self.workspace.restarted = True
        self.workspace.potential_path = None
        self.workspace.empty_spheres_added = None
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
        had_result = self.workspace.result is not None
        self.workspace.result = None
        directory_changed = self._set_directory(directory)
        self.workspace.input_parameters = parameters
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return DocumentChange.APPLIED

    def change_directory(self, directory: str | None) -> None:
        """Change directory and invalidate any result bound to the old one."""
        if not self._set_directory(directory):
            return
        had_result = self.workspace.result is not None
        self.workspace.result = None
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
        """Install a fully loaded external result as a new document."""
        adoption = self._result_adoption(loaded)
        if not self._generation_is_current(expected_generation):
            return replace(adoption, adopted=False)

        self._remember_result(loaded.result, replace_history=True)
        self.workspace.atoms = loaded.atoms
        self.workspace.input_parameters = loaded.input_parameters
        self.workspace.potential_path = (
            str(loaded.potential_path)
            if loaded.atoms is not None
            else None
        )
        self.workspace.empty_spheres_added = None
        self.workspace.restarted = False
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
        """Adopt a result if its calculation epoch is still current."""
        adoption = self._result_adoption(loaded)
        if not self._calculation_generation_is_current(expected_generation):
            return replace(adoption, adopted=False)

        if loaded.atoms is not None:
            self.workspace.atoms = loaded.atoms
            self.workspace.potential_path = str(loaded.potential_path)
            if _result_is_scf(loaded.result):
                self.workspace.restarted = False
        self._remember_result(loaded.result)
        self._result_changed()

        if loaded.atoms is not None:
            self.structureChanged.emit(loaded.atoms)
        self.resultChanged.emit(loaded.result)
        return adoption

    def reset(self) -> None:
        self._clear_result_history()
        self.workspace.atoms = None
        self.workspace.potential_path = None
        self.workspace.input_parameters = None
        self.workspace.empty_spheres_added = None
        self.workspace.restarted = False
        self._set_directory(None)
        self._changed()
        self.resultChanged.emit(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)

    def use_for_new_calculation(
        self, *, expected_generation: Generation | None = None
    ) -> DocumentChange:
        """Start a new calculation from the current structure and potential.

        Clear only the current result and mark the workspace as restarted.
        The structure, potential path, empty-sphere state and result history are
        preserved as input/context for the new calculation.
        """
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        had_result = self.workspace.result is not None
        self.workspace.result = None
        self.workspace.restarted = True
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
        """Commit one explicit empty-sphere search/recalculation transactionally."""
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        source = self.atoms
        if source is None:
            raise ValueError("No structure is loaded.")

        previous_count = self.workspace.empty_spheres_added or 0
        updated, count, structure_changed = edit(source.copy(), previous_count)
        count = int(count)
        if count < 0:
            raise ValueError("Empty-sphere count cannot be negative.")
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        result = EmptySpheresResult(found=count, parameters=parameters or {})
        self.workspace.empty_spheres_added = count
        if structure_changed:
            self._clear_result_history()
            self.workspace.atoms = updated
            self.workspace.potential_path = None
            self.workspace.restarted = True
            self._changed()
        self._remember_result(result)

        self.structureChanged.emit(updated if structure_changed else source)
        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
