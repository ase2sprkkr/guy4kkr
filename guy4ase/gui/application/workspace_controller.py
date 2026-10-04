"""Semantic document transitions over the shared GUI workspace."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

from ase.io import read as ase_read
from ase.io import write as ase_write
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.outputs.task_result import TaskResult
from ase2sprkkr.potentials.potentials import Potential
from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.workspace import WorkspaceState

_KEEP_DIRECTORY = object()
_T = TypeVar("_T")


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
    adopted: bool = True


PreparedStructureLoad = tuple[Path, Any]
PreparedResultLoad = tuple[Any, ResultAdoption, Any, str]
PreparedCalculationResult = tuple[Any, ResultAdoption, Any]


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

    def read_structure(
        self,
        reader: Callable[[Any], _T],
        *,
        reason: str = "reading the structure for an editor",
    ) -> tuple[int, _T] | Busy:
        """Create a revision-tagged snapshot derived from shared Atoms."""

        def read() -> tuple[int, _T]:
            return self._generation, reader(self.workspace.atoms)

        return self._structure_gate.try_call(reason, read)

    def create_calculation_request(self) -> CalculationRequest | Busy:
        """Borrow Atoms and capture independent calculation inputs."""

        def capture() -> CalculationRequest:
            atoms = self.workspace.atoms
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

        return self._structure_gate.try_call(
            "creating a calculation request", capture
        )

    def _generation_is_current(self, expected: int | None) -> bool:
        return expected is None or expected == self._generation

    def _changed(self) -> None:
        self._generation += 1

    def replace_structure(
        self,
        atoms: Any,
        *,
        potential_path: str | None = None,
        expected_generation: int | None = None,
    ) -> DocumentChange | Busy:
        def change() -> tuple[DocumentChange, bool]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False
            had_result = self.workspace.result is not None
            self.workspace.result = None
            self.workspace.atoms = atoms
            self.workspace.potential_path = potential_path
            self._changed()
            return DocumentChange.APPLIED, had_result

        attempt = self._structure_gate.try_call("changing the structure", change)
        if isinstance(attempt, Busy):
            return attempt
        status, had_result = attempt
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            self.structureChanged.emit(atoms)
        return status

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_generation: int,
        preserve_potential_path: bool = False,
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
            if not preserve_potential_path:
                self.workspace.potential_path = None
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
        if directory is not _KEEP_DIRECTORY:
            self.workspace.directory = directory
        self.workspace.input_parameters = parameters
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        if directory is not _KEEP_DIRECTORY:
            self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return DocumentChange.APPLIED

    def change_working_directory(self, directory: str | None) -> None:
        """Change directory metadata without invalidating calculations."""
        self.workspace.directory = directory
        self.directoryChanged.emit(directory)

    @staticmethod
    def prepare_structure_load(
        file_path: str | Path,
    ) -> PreparedStructureLoad:
        """Parse a structure exactly once, without touching the document."""
        resolved = Path(file_path).resolve()
        return resolved, ase_read(resolved)

    def adopt_loaded_structure(
        self,
        prepared: PreparedStructureLoad,
        *,
        expected_generation: int,
    ) -> DocumentChange | Busy:
        """Commit an already parsed structure under the structure gate."""
        resolved, atoms = prepared

        def commit() -> tuple[DocumentChange, bool, str | None]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False, None
            had_result = self.workspace.result is not None
            directory = str(resolved.parent)
            self.workspace.result = None
            self.workspace.directory = directory
            self.workspace.atoms = atoms
            self.workspace.potential_path = (
                str(resolved)
                if resolved.suffix.lower() in {".pot", ".pot_new"}
                else None
            )
            self._changed()
            return DocumentChange.APPLIED, had_result, directory

        attempt = self._structure_gate.try_call(
            "loading a structure from a file", commit
        )
        if isinstance(attempt, Busy):
            return attempt
        status, had_result, directory = attempt
        if status is DocumentChange.STALE:
            return status
        if had_result:
            self.resultChanged.emit(None)
        assert directory is not None
        self.directoryChanged.emit(directory)
        self.structureChanged.emit(atoms)
        return status

    def load_input_parameters(self, file_path: str | Path) -> InputParameters:
        """Parse and commit input data without taking the structure lock."""
        resolved = Path(file_path).resolve()
        parameters = InputParameters.from_file(resolved)
        had_result = self.workspace.result is not None
        directory = str(resolved.parent)
        self.workspace.result = None
        self.workspace.directory = directory
        self.workspace.input_parameters = parameters
        self._changed()
        if had_result:
            self.resultChanged.emit(None)
        self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return parameters

    def save_structure(self, file_path: str | Path) -> Path | Busy:
        """Write directly from shared Atoms while holding the structure lock."""
        resolved = Path(file_path).resolve()

        def save() -> Path:
            if self.workspace.atoms is None:
                raise ValueError("No structure is loaded.")
            ase_write(resolved, self.workspace.atoms)
            return resolved

        return self._structure_gate.try_call("saving the structure", save)

    def save_input_parameters(self, file_path: str | Path) -> Path:
        """Write independent input data without taking the structure lock."""
        resolved = Path(file_path).resolve()
        if self.workspace.input_parameters is None:
            raise ValueError("No input parameters are loaded.")
        self.workspace.input_parameters.to_file(resolved)
        return resolved

    def prepare_result_load(
        self, file_path: str | Path
    ) -> PreparedResultLoad:
        """Parse an external result and its potential exactly once."""
        resolved = Path(file_path).resolve()
        result = TaskResult.from_file(resolved)
        output, potential = self._result_artifacts(result, resolved.parent)
        output = output or resolved
        atoms, potential_error = self._load_result_potential(potential)
        directory = str(output.parent.resolve())
        adoption = ResultAdoption(output, potential, potential_error)
        return result, adoption, atoms, directory

    def adopt_loaded_result(
        self,
        prepared: PreparedResultLoad,
        *,
        expected_generation: int,
    ) -> ResultAdoption | Busy:
        """Commit one already parsed external result under the structure gate."""
        result, adoption, atoms, directory = prepared

        def commit() -> bool:
            if not self._generation_is_current(expected_generation):
                return False
            self.workspace.result = result
            self.workspace.atoms = atoms
            self.workspace.potential_path = (
                str(adoption.potential_path) if atoms is not None else None
            )
            self.workspace.directory = directory
            self._changed()
            return True

        attempt = self._structure_gate.try_call(
            "loading a calculation result", commit
        )
        if isinstance(attempt, Busy):
            return attempt
        if not attempt:
            return replace(adoption, adopted=False)
        self.structureChanged.emit(atoms)
        self.directoryChanged.emit(directory)
        self.resultChanged.emit(result)
        return adoption

    @staticmethod
    def _result_path(result: Any, key: str) -> Path | None:
        try:
            if hasattr(result, "files") and key in result.files:
                value = result.path_to(key)
                return Path(value) if value else None
        except Exception:  # noqa: BLE001 - optional third-party adapter
            return None
        return None

    @staticmethod
    def _resolve_result_path(
        path: str | Path | None,
        result: Any,
        fallback_directory: str | Path | None,
    ) -> Path | None:
        if not path:
            return None
        resolved = Path(path)
        if not resolved.is_absolute():
            base = getattr(result, "directory", None) or fallback_directory
            if base:
                resolved = Path(base) / resolved
        return resolved.resolve()

    def _result_artifacts(
        self,
        result: Any,
        fallback_directory: str | Path | None,
    ) -> tuple[Path | None, Path | None]:
        output = self._result_path(result, "output")
        if output is None:
            output = self._resolve_result_path(
                getattr(result, "output_file", None), result, fallback_directory
            )
        else:
            output = self._resolve_result_path(output, result, fallback_directory)

        potential = self._result_path(result, "converged")
        if potential is None:
            potential = self._result_path(result, "potential")
        if potential is None:
            try:
                potential = getattr(result, "potential_filename", None)
            except Exception:  # noqa: BLE001
                potential = None
        potential = self._resolve_result_path(
            potential,
            result,
            fallback_directory or self.workspace.directory,
        )
        return output, potential

    @staticmethod
    def _load_result_potential(
        potential: Path | None,
    ) -> tuple[Any | None, Exception | None]:
        if potential is not None and potential.is_file():
            try:
                resolved = potential.resolve()
                return Potential.from_file(str(resolved)).atoms, None
            except Exception as exc:  # noqa: BLE001
                return None, exc
        return None, None

    def prepare_calculation_result(
        self,
        result: Any,
        *,
        expected_generation: int,
        fallback_directory: str | Path | None = None,
    ) -> PreparedCalculationResult:
        """Resolve and parse calculation artifacts exactly once."""
        if not self._generation_is_current(expected_generation):
            output, potential = self._result_artifacts(
                result, fallback_directory
            )
            return result, ResultAdoption(output, potential, adopted=False), None

        output, potential = self._result_artifacts(result, fallback_directory)
        atoms, potential_error = self._load_result_potential(potential)
        return result, ResultAdoption(output, potential, potential_error), atoms

    def adopt_calculation_result(
        self,
        prepared: PreparedCalculationResult,
        *,
        expected_generation: int,
    ) -> ResultAdoption | Busy:
        """Adopt only a result produced from the current document revision."""
        result, prepared_adoption, atoms = prepared
        if not prepared_adoption.adopted:
            return prepared_adoption

        def commit() -> ResultAdoption:
            if not self._generation_is_current(expected_generation):
                return replace(prepared_adoption, adopted=False)
            if atoms is not None:
                self.workspace.atoms = atoms
                self.workspace.potential_path = str(
                    prepared_adoption.potential_path
                )
            self.workspace.result = result
            self._changed()
            return prepared_adoption

        # Missing/unreadable potential preserves Atoms, so this is metadata-only.
        if atoms is None:
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
        if atoms is not None:
            self.structureChanged.emit(atoms)
        self.resultChanged.emit(result)
        return adoption

    def reset(self) -> None | Busy:
        def clear() -> None:
            self.workspace.result = None
            self.workspace.atoms = None
            self.workspace.potential_path = None
            self.workspace.input_parameters = None
            self.workspace.directory = None
            self._changed()

        attempt = self._structure_gate.try_call("clearing the structure", clear)
        if isinstance(attempt, Busy):
            return attempt
        self.resultChanged.emit(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)
        return None

    def restart_scf(
        self, *, expected_generation: int | None = None
    ) -> DocumentChange | Busy:
        return self.apply_structure_edit(
            self._restart_atoms,
            expected_generation=(
                self._generation
                if expected_generation is None
                else expected_generation
            ),
            preserve_potential_path=True,
            reason="restarting SCF",
        )

    @staticmethod
    def _restart_atoms(atoms: Any) -> Any:
        atoms.potential.SCF_INFO.SCFSTATUS = "START"
        return atoms
