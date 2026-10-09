"""Semantic document transitions over the shared GUI workspace."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState

_KEEP_DIRECTORY = object()
_T = TypeVar("_T")


def _result_is_scf(result: Any) -> bool:
    """Return whether a live calculation result belongs to an SCF task."""
    try:
        return str(result.task_name).strip().lower() == "scf"
    except (AttributeError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Busy:
    """A nonblocking structure operation could not enter the gate."""

    requested_reason: str
    active_reason: str


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive document command."""

    APPLIED = auto()
    STALE = auto()


class StructureAccessGate:
    """Serialize physical access to the workspace's shared mutable Atoms."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state_lock = Lock()
        self._active_reason: str | None = None

    @property
    def active_reason(self) -> str | None:
        with self._state_lock:
            return self._active_reason

    def locked(self) -> bool:
        return self._lock.locked()

    def try_call(self, reason: str, callback: Callable[[], _T]) -> _T | Busy:
        """Run immediately under the structure lock or describe its owner."""
        if not self._lock.acquire(blocking=False):
            return Busy(
                requested_reason=reason,
                active_reason=self.active_reason or "another structure operation",
            )
        return self._run_locked(reason, callback)

    def call(self, reason: str, callback: Callable[[], _T]) -> _T:
        """Wait for the structure lock and run a worker operation under it."""
        self._lock.acquire()
        return self._run_locked(reason, callback)

    def _run_locked(self, reason: str, callback: Callable[[], _T]) -> _T:
        with self._state_lock:
            self._active_reason = reason
        try:
            return callback()
        finally:
            with self._state_lock:
                self._active_reason = None
            self._lock.release()


@dataclass(frozen=True)
class CalculationRequest:
    """Values captured when the user asks to start a calculation.

    ``atoms`` is deliberately borrowed, not copied. ``input_parameters`` is an
    independent value copy so preparation cannot mutate the editor document.
    """

    atoms: Any
    input_parameters: Any
    directory: str
    generation: int


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

    The structure gate has one narrow purpose: it protects physical access to
    the shared mutable ``Atoms`` instance. The revision independently rejects
    stale editor drafts and calculation results.
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
        self._structure_gate = StructureAccessGate()
        self._generation = 0

    @property
    def structure_gate(self) -> StructureAccessGate:
        return self._structure_gate

    @property
    def generation(self) -> int:
        return self._generation

    @pyqtSlot(object)
    def notify_structure_prepared(self, atoms: Any) -> None:
        """Refresh the current borrowed structure after worker preparation.

        Preparation may mutate Atoms even when it fails. This notification
        does not advance the revision or invalidate the calculation request.
        Checking identity does not read Atoms data; observers protect their
        own structure reads through the gate.
        """
        if self.workspace.atoms is atoms:
            self.structureChanged.emit(atoms)

    def access_structure(
        self,
        operation: Callable[[Any], _T],
        *,
        reason: str,
    ) -> _T | Busy:
        """Run an operation with exclusive access to shared Atoms.

        The callback may inspect or serialize the borrowed structure, but
        document mutations belong in the named controller transitions.
        """
        return self._structure_gate.try_call(
            reason,
            lambda: operation(self.workspace.atoms),
        )

    def read_structure(
        self,
        reader: Callable[[Any], _T],
        *,
        reason: str = "reading the structure for an editor",
    ) -> tuple[int, _T] | Busy:
        """Create a revision-tagged snapshot derived from shared Atoms."""

        return self.access_structure(
            lambda atoms: (self._generation, reader(atoms)),
            reason=reason,
        )

    def create_calculation_request(self) -> CalculationRequest | Busy:
        """Borrow Atoms and capture independent calculation inputs."""

        def capture(atoms: Any) -> CalculationRequest:
            parameters = self.workspace.input_parameters
            directory = self.workspace.directory
            if atoms is None or parameters is None or not directory:
                raise ValueError(
                    "Structure, input parameters and directory are required."
                )
            return CalculationRequest(
                atoms=atoms,
                input_parameters=parameters.copy(copy_values=True),
                directory=directory,
                generation=self._generation,
            )

        return self.access_structure(
            capture,
            reason="creating a calculation request",
        )

    def _generation_is_current(self, expected: int | None) -> bool:
        return expected is None or expected == self._generation

    def _changed(self) -> None:
        self._generation += 1

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
        expected_generation: int | None = None,
        restarted: bool = False,
    ) -> DocumentChange | Busy:
        def change() -> tuple[DocumentChange, bool, bool]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False, False
            had_result = self.workspace.result is not None
            self.workspace.result = None
            self.workspace.atoms = atoms
            self.workspace.potential_path = potential_path
            self.workspace.empty_spheres_added = None
            self.workspace.restarted = restarted
            directory_changed = self._set_directory(directory)
            self._changed()
            return DocumentChange.APPLIED, had_result, directory_changed

        attempt = self._structure_gate.try_call("changing the structure", change)
        if isinstance(attempt, Busy):
            return attempt
        status, had_result, directory_changed = attempt
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            if directory_changed:
                self.directoryChanged.emit(directory)
            self.structureChanged.emit(atoms)
        return status

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_generation: int,
        preserve_potential_path: bool = False,
        preserve_empty_spheres: bool = False,
        reason: str = "applying structure changes",
    ) -> DocumentChange | Busy:
        def change() -> tuple[DocumentChange, bool, Any]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False, None
            if self.workspace.atoms is None:
                raise ValueError("No structure is loaded.")
            atoms = edit(self.workspace.atoms)
            if atoms is None:
                raise ValueError("A confirmed structure edit returned no structure.")
            had_result = self.workspace.result is not None
            self.workspace.result = None
            self.workspace.atoms = atoms
            self.workspace.restarted = True
            if not preserve_potential_path:
                self.workspace.potential_path = None
            if not preserve_empty_spheres:
                self.workspace.empty_spheres_added = None
            self._changed()
            return DocumentChange.APPLIED, had_result, atoms

        attempt = self._structure_gate.try_call(reason, change)
        if isinstance(attempt, Busy):
            return attempt
        status, had_result, atoms = attempt
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            self.structureChanged.emit(atoms)
        return status

    def replace_input_parameters(
        self,
        parameters: Any,
        *,
        directory: Any = _KEEP_DIRECTORY,
        expected_generation: int | None = None,
    ) -> DocumentChange:
        """Replace independent input data without taking the structure lock."""
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
        expected_generation: int,
    ) -> ResultAdoption | Busy:
        """Install a fully loaded external result as a new document."""
        adoption = self._result_adoption(loaded)

        def commit() -> tuple[bool, bool]:
            if not self._generation_is_current(expected_generation):
                return False, False
            self.workspace.result = loaded.result
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
            return True, directory_changed

        attempt = self._structure_gate.try_call(
            "loading a calculation result", commit
        )
        if isinstance(attempt, Busy):
            return attempt
        adopted, directory_changed = attempt
        if not adopted:
            return replace(adoption, adopted=False)
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
        expected_generation: int,
    ) -> ResultAdoption | Busy:
        """Adopt a loaded result produced from the current revision."""
        prepared_adoption = self._result_adoption(loaded)

        def commit() -> ResultAdoption:
            if not self._generation_is_current(expected_generation):
                return replace(prepared_adoption, adopted=False)
            if loaded.atoms is not None:
                self.workspace.atoms = loaded.atoms
                self.workspace.potential_path = str(
                    loaded.potential_path
                )
                if _result_is_scf(loaded.result):
                    self.workspace.restarted = False
            self.workspace.result = loaded.result
            self._changed()
            return prepared_adoption

        # Missing/unreadable potential preserves Atoms, so this is metadata-only.
        if loaded.atoms is None:
            adoption = commit()
        else:
            attempt = self._structure_gate.try_call(
                "adopting a calculation result", commit
            )
            if isinstance(attempt, Busy):
                return attempt
            adoption = attempt

        if not adoption.adopted:
            return adoption
        if loaded.atoms is not None:
            self.structureChanged.emit(loaded.atoms)
        self.resultChanged.emit(loaded.result)
        return adoption

    def reset(self) -> None | Busy:
        def clear() -> None:
            self.workspace.result = None
            self.workspace.atoms = None
            self.workspace.potential_path = None
            self.workspace.input_parameters = None
            self.workspace.empty_spheres_added = None
            self.workspace.restarted = False
            self._set_directory(None)
            self._changed()

        attempt = self._structure_gate.try_call("clearing the structure", clear)
        if isinstance(attempt, Busy):
            return attempt
        self.resultChanged.emit(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)
        return None

    def use_for_new_calculation(
        self, *, expected_generation: int | None = None
    ) -> DocumentChange | Busy:
        """Reset the SCF stage while keeping the current starting density."""
        return self.apply_structure_edit(
            self._restart_atoms,
            expected_generation=(
                self._generation
                if expected_generation is None
                else expected_generation
            ),
            preserve_potential_path=True,
            preserve_empty_spheres=True,
            reason="preparing the structure for a new calculation",
        )

    def update_empty_spheres(
        self,
        edit: Callable[[Any, int], tuple[Any, int]],
        *,
        expected_generation: int,
    ) -> DocumentChange | Busy:
        """Commit one explicit empty-sphere search/recalculation."""

        def change() -> tuple[DocumentChange, bool, bool, Any]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False, False, None
            atoms = self.workspace.atoms
            if atoms is None:
                raise ValueError("No structure is loaded.")
            previous_count = self.workspace.empty_spheres_added or 0
            updated, count = edit(atoms, previous_count)
            count = int(count)
            if count < 0:
                raise ValueError("Empty-sphere count cannot be negative.")

            structure_changed = updated is not atoms
            had_result = structure_changed and self.workspace.result is not None
            self.workspace.empty_spheres_added = count
            if structure_changed:
                self.workspace.result = None
                self.workspace.atoms = updated
                self.workspace.potential_path = None
                self.workspace.restarted = True
                self._changed()
            return DocumentChange.APPLIED, structure_changed, had_result, updated

        attempt = self._structure_gate.try_call(
            "updating empty spheres", change
        )
        if isinstance(attempt, Busy):
            return attempt
        status, _structure_changed, had_result, atoms = attempt
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            # A no-op search still changes workflow state (None -> 0), so
            # refresh observers without inventing a new structure revision.
            self.structureChanged.emit(atoms)
        return status

    @staticmethod
    def _restart_atoms(atoms: Any) -> Any:
        atoms.potential.SCF_INFO.SCFSTATUS = "START"
        return atoms
