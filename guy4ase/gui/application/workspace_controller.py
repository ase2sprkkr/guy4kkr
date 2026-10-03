"""Application operations over the shared workspace document."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from threading import Lock
from typing import Any, Generic, TypeVar

from ase.io import read as ase_read
from ase.io import write as ase_write
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.outputs.task_result import TaskResult
from ase2sprkkr.potentials.potentials import Potential
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from guy4ase.gui.application.workspace import WorkspaceState

_KEEP_DIRECTORY = object()
_T = TypeVar("_T")


@dataclass(frozen=True)
class Completed(Generic[_T]):
    """A gate operation completed while owning the workspace lock."""

    value: _T


@dataclass(frozen=True)
class Busy:
    """A nonblocking operation could not enter the workspace gate."""

    requested_reason: str
    active_reason: str


class DocumentChange(Enum):
    """Semantic result of a generation-sensitive document command."""

    APPLIED = auto()
    STALE = auto()


class WorkspaceAccessGate:
    """Own the single workspace mutex and describe its current operation."""

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

    def try_call(
        self,
        reason: str,
        callback: Callable[[], _T],
    ) -> Completed[_T] | Busy:
        """Run immediately under the lock or report its current owner."""
        if not self._lock.acquire(blocking=False):
            return Busy(
                requested_reason=reason,
                active_reason=self.active_reason or "another workspace operation",
            )
        return Completed(self._run_locked(reason, callback))

    def call(self, reason: str, callback: Callable[[], _T]) -> _T:
        """Wait for the lock and run a worker operation under it."""
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


class WorkspaceController(QObject):
    """Own semantic transitions over borrowed workspace objects.

    Confirmed changes return through this controller. The access gate protects
    shared ``Atoms`` and other document facets; signals are emitted only after
    the gate has released its mutex.
    """

    structureChanged = pyqtSignal(object)
    inputParametersChanged = pyqtSignal(object)
    directoryChanged = pyqtSignal(object)
    resultChanged = pyqtSignal(object)
    activeRunsChanged = pyqtSignal(int)

    def __init__(
        self,
        workspace: WorkspaceState | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace = workspace or WorkspaceState()
        self._access_gate = WorkspaceAccessGate()
        self._generation = 0
        self._active_runs: set[Any] = set()

    @property
    def access_gate(self) -> WorkspaceAccessGate:
        return self._access_gate

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def active_run_count(self) -> int:
        return len(self._active_runs)

    def try_structure_access(
        self,
        reader: Callable[[], _T],
        *,
        reason: str = "refreshing the structure view",
    ) -> Completed[_T] | Busy:
        """Try a short, consistent GUI read without blocking Qt."""
        return self._access_gate.try_call(reason, reader)

    def read_structure(
        self,
        reader: Callable[[Any], _T],
        *,
        reason: str = "reading the structure for an editor",
    ) -> Completed[tuple[int, _T]] | Busy:
        def read(workspace: WorkspaceState) -> _T:
            return reader(workspace.atoms)

        return self.read_workspace(read, reason=reason)

    def read_workspace(
        self,
        reader: Callable[[WorkspaceState], _T],
        *,
        reason: str = "reading workspace data",
    ) -> Completed[tuple[int, _T]] | Busy:
        """Create a short-lived editor/view snapshot under the shared gate."""
        def read() -> tuple[int, _T]:
            return self._generation, reader(self.workspace)

        return self._access_gate.try_call(reason, read)

    def create_calculation_request(self) -> Completed[CalculationRequest] | Busy:
        """Capture one request without copying its potentially large atoms."""

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

        return self._access_gate.try_call(
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
    ) -> Completed[DocumentChange] | Busy:
        def change() -> tuple[DocumentChange, bool]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False
            had_result = self.workspace.result is not None
            self.workspace.result = None
            self.workspace.atoms = atoms
            self.workspace.potential_path = potential_path
            self._changed()
            return DocumentChange.APPLIED, had_result

        attempt = self._access_gate.try_call("changing the structure", change)
        if isinstance(attempt, Busy):
            return attempt
        status, had_result = attempt.value
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            self.structureChanged.emit(atoms)
        return Completed(status)

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_generation: int,
        preserve_potential_path: bool = False,
        reason: str = "applying structure changes",
    ) -> Completed[DocumentChange] | Busy:
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

        attempt = self._access_gate.try_call(reason, change)
        if isinstance(attempt, Busy):
            return attempt
        status, had_result, atoms = attempt.value
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            self.structureChanged.emit(atoms)
        return Completed(status)

    def replace_input_parameters(
        self,
        parameters: Any,
        *,
        directory: Any = _KEEP_DIRECTORY,
        expected_generation: int | None = None,
    ) -> Completed[DocumentChange] | Busy:
        def change() -> tuple[DocumentChange, bool]:
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE, False
            had_result = self.workspace.result is not None
            self.workspace.result = None
            if directory is not _KEEP_DIRECTORY:
                self.workspace.directory = directory
            self.workspace.input_parameters = parameters
            self._changed()
            return DocumentChange.APPLIED, had_result

        attempt = self._access_gate.try_call(
            "changing calculation parameters", change
        )
        if isinstance(attempt, Busy):
            return attempt
        status, had_result = attempt.value
        if status is DocumentChange.APPLIED:
            if had_result:
                self.resultChanged.emit(None)
            if directory is not _KEEP_DIRECTORY:
                self.directoryChanged.emit(directory)
            self.inputParametersChanged.emit(parameters)
        return Completed(status)

    def change_working_directory(
        self, directory: str | None
    ) -> Completed[None] | Busy:
        def change() -> None:
            self.workspace.directory = directory
            self._changed()

        attempt = self._access_gate.try_call(
            "changing the working directory", change
        )
        if isinstance(attempt, Busy):
            return attempt
        self.directoryChanged.emit(directory)
        return attempt

    def load_structure(self, file_path: str | Path) -> Completed[Any] | Busy:
        resolved = Path(file_path).resolve()

        def load() -> tuple[Any, bool, str]:
            atoms = ase_read(resolved)
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
            return atoms, had_result, directory

        attempt = self._access_gate.try_call(
            "loading a structure from a file", load
        )
        if isinstance(attempt, Busy):
            return attempt
        atoms, had_result, directory = attempt.value
        if had_result:
            self.resultChanged.emit(None)
        self.directoryChanged.emit(directory)
        self.structureChanged.emit(atoms)
        return Completed(atoms)

    def load_input_parameters(
        self, file_path: str | Path
    ) -> Completed[InputParameters] | Busy:
        resolved = Path(file_path).resolve()

        def load() -> tuple[InputParameters, bool, str]:
            parameters = InputParameters.from_file(resolved)
            had_result = self.workspace.result is not None
            directory = str(resolved.parent)
            self.workspace.result = None
            self.workspace.directory = directory
            self.workspace.input_parameters = parameters
            self._changed()
            return parameters, had_result, directory

        attempt = self._access_gate.try_call(
            "loading calculation parameters from a file", load
        )
        if isinstance(attempt, Busy):
            return attempt
        parameters, had_result, directory = attempt.value
        if had_result:
            self.resultChanged.emit(None)
        self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return Completed(parameters)

    def save_structure(self, file_path: str | Path) -> Completed[Path] | Busy:
        resolved = Path(file_path).resolve()

        def save() -> Path:
            if self.workspace.atoms is None:
                raise ValueError("No structure is loaded.")
            ase_write(resolved, self.workspace.atoms)
            return resolved

        return self._access_gate.try_call("saving the structure", save)

    def save_input_parameters(
        self, file_path: str | Path
    ) -> Completed[Path] | Busy:
        resolved = Path(file_path).resolve()

        def save() -> Path:
            if self.workspace.input_parameters is None:
                raise ValueError("No input parameters are loaded.")
            self.workspace.input_parameters.to_file(resolved)
            return resolved

        return self._access_gate.try_call(
            "saving calculation parameters", save
        )

    def load_result(
        self, file_path: str | Path
    ) -> Completed[ResultAdoption] | Busy:
        resolved = Path(file_path).resolve()

        def load() -> tuple[ResultAdoption, Any, Any, str]:
            result = TaskResult.from_file(resolved)
            output, potential = self._result_artifacts(result, resolved.parent)
            output = output or resolved
            atoms, potential_error = self._load_result_potential(potential)
            directory = str(output.parent.resolve())
            self.workspace.result = result
            self.workspace.atoms = atoms
            self.workspace.potential_path = (
                str(potential) if atoms is not None else None
            )
            self.workspace.directory = directory
            self._changed()
            return (
                ResultAdoption(output, potential, potential_error),
                result,
                atoms,
                directory,
            )

        attempt = self._access_gate.try_call(
            "loading a calculation result", load
        )
        if isinstance(attempt, Busy):
            return attempt
        adoption, result, atoms, directory = attempt.value
        self.structureChanged.emit(atoms)
        self.directoryChanged.emit(directory)
        self.resultChanged.emit(result)
        return Completed(adoption)

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

    def adopt_calculation_result(
        self,
        result: Any,
        *,
        expected_generation: int,
    ) -> Completed[ResultAdoption] | Busy:
        def adopt() -> tuple[ResultAdoption, Any, Any, str | None]:
            if not self._generation_is_current(expected_generation):
                output, potential = self._result_artifacts(
                    result, getattr(result, "directory", None)
                )
                return ResultAdoption(output, potential, adopted=False), None, None, None

            output, potential = self._result_artifacts(
                result, self.workspace.directory
            )
            atoms, potential_error = self._load_result_potential(potential)
            if atoms is not None:
                self.workspace.atoms = atoms
                self.workspace.potential_path = str(potential.resolve())
            directory_value = (
                output.parent
                if output is not None
                else getattr(result, "directory", None)
            )
            directory = None
            if directory_value is not None:
                directory = str(Path(directory_value).resolve())
                self.workspace.directory = directory
            self.workspace.result = result
            self._changed()
            return (
                ResultAdoption(output, potential, potential_error),
                result,
                atoms,
                directory,
            )

        attempt = self._access_gate.try_call(
            "adopting a calculation result", adopt
        )
        if isinstance(attempt, Busy):
            return attempt
        adoption, adopted_result, atoms, directory = attempt.value
        if not adoption.adopted:
            return Completed(adoption)
        if atoms is not None:
            self.structureChanged.emit(atoms)
        if directory is not None:
            self.directoryChanged.emit(directory)
        self.resultChanged.emit(adopted_result)
        return Completed(adoption)

    def reset(self) -> Completed[None] | Busy:
        def clear() -> None:
            self.workspace.result = None
            self.workspace.atoms = None
            self.workspace.potential_path = None
            self.workspace.input_parameters = None
            self.workspace.directory = None
            self._changed()

        attempt = self._access_gate.try_call(
            "clearing the workspace", clear
        )
        if isinstance(attempt, Busy):
            return attempt
        self.resultChanged.emit(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)
        return attempt

    def restart_scf(
        self, *, expected_generation: int | None = None
    ) -> Completed[DocumentChange] | Busy:
        return self.apply_structure_edit(
            self._restart_atoms,
            expected_generation=(
                self._generation
                if expected_generation is None
                else expected_generation
            ),
            preserve_potential_path=True,
            reason="restart SCF",
        )

    @staticmethod
    def _restart_atoms(atoms: Any) -> Any:
        atoms.potential.SCF_INFO.SCFSTATUS = "START"
        return atoms

    @pyqtSlot(object)
    def register_active_run(self, run_id: Any) -> None:
        before = len(self._active_runs)
        self._active_runs.add(run_id)
        if len(self._active_runs) != before:
            self.activeRunsChanged.emit(len(self._active_runs))

    @pyqtSlot(object)
    def unregister_active_run(self, run_id: Any) -> None:
        before = len(self._active_runs)
        self._active_runs.discard(run_id)
        if len(self._active_runs) != before:
            self.activeRunsChanged.emit(len(self._active_runs))

    @pyqtSlot(object)
    def try_publish_preparation_refresh(
        self, atoms: Any
    ) -> Completed[None] | Busy:
        def is_current_structure() -> bool:
            return self.workspace.atoms is atoms

        attempt = self._access_gate.try_call(
            "refreshing the structure after calculation preparation",
            is_current_structure,
        )
        if isinstance(attempt, Busy):
            return attempt
        if attempt.value:
            self.structureChanged.emit(atoms)
        return Completed(None)
