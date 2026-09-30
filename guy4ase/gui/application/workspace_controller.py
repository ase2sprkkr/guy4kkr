"""Application operations over the shared workspace document."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase.io import read as ase_read
from ase.io import write as ase_write
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.outputs.task_result import TaskResult
from ase2sprkkr.potentials.potentials import Potential
from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.workspace import WorkspaceState


@dataclass(frozen=True)
class ResultAdoption:
    """Artifacts and a non-fatal potential error from adopting a result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None


class WorkspaceController(QObject):
    """Mutate one workspace and publish its document-level changes.

    The controller deliberately knows neither dialogs nor concrete views.
    File choosers, error presentation and widget refreshes remain UI concerns.
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

    def set_structure(
        self, atoms: Any, *, potential_path: str | None = None
    ) -> None:
        self.workspace.atoms = atoms
        self.workspace.potential_path = potential_path
        self.structureChanged.emit(atoms)

    def set_input_parameters(self, parameters: Any) -> None:
        self.workspace.input_parameters = parameters
        self.inputParametersChanged.emit(parameters)

    def set_directory(self, directory: str | None) -> None:
        if self.workspace.directory == directory:
            return
        self.workspace.directory = directory
        self.directoryChanged.emit(directory)

    def load_structure(self, file_path: str | Path) -> Any:
        """Load a structure and publish it as the current document."""
        resolved = Path(file_path).resolve()
        atoms = ase_read(resolved)
        self.set_directory(str(resolved.parent))
        self.set_structure(
            atoms,
            potential_path=(
                str(resolved)
                if resolved.suffix.lower() in {".pot", ".pot_new"}
                else None
            ),
        )
        return atoms

    def load_input_parameters(self, file_path: str | Path) -> InputParameters:
        """Load input parameters and publish them as the current document."""
        resolved = Path(file_path).resolve()
        parameters = InputParameters.from_file(resolved)
        self.set_directory(str(resolved.parent))
        self.set_input_parameters(parameters)
        return parameters

    def save_structure(self, file_path: str | Path) -> Path:
        """Write the current structure to an absolute path."""
        if self.workspace.atoms is None:
            raise ValueError("No structure is loaded.")
        resolved = Path(file_path).resolve()
        ase_write(resolved, self.workspace.atoms)
        return resolved

    def save_input_parameters(self, file_path: str | Path) -> Path:
        """Write the current input parameters to an absolute path."""
        if self.workspace.input_parameters is None:
            raise ValueError("No input parameters are loaded.")
        resolved = Path(file_path).resolve()
        self.workspace.input_parameters.to_file(resolved)
        return resolved

    def load_result(self, file_path: str | Path) -> ResultAdoption:
        """Load a result file and adopt its document-level state."""
        resolved = Path(file_path).resolve()
        result = TaskResult.from_file(resolved)
        adoption = self.adopt_result(
            result,
            fallback_directory=resolved.parent,
        )
        if adoption.output_path is not None:
            return adoption
        return ResultAdoption(
            output_path=resolved,
            potential_path=adoption.potential_path,
            potential_error=adoption.potential_error,
        )

    @staticmethod
    def _result_path(result: Any, key: str) -> Path | None:
        try:
            if hasattr(result, "files") and key in result.files:
                value = result.path_to(key)
                return Path(value) if value else None
        # Third-party result adapters may expose lazy mappings/path resolvers
        # with backend-specific exceptions. A missing artifact is non-fatal.
        except Exception:  # noqa: BLE001
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

    def adopt_result(
        self,
        result: Any,
        *,
        fallback_directory: str | Path | None = None,
    ) -> ResultAdoption:
        """Adopt a result, including any readable converged potential.

        Result and directory changes are committed before potential loading.
        A potential reader failure is returned to the UI without rolling back
        the already adopted result.
        """
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
            except Exception:  # noqa: BLE001 - optional backend property
                potential = None
        potential = self._resolve_result_path(
            potential, result, fallback_directory or self.workspace.directory
        )

        self.workspace.result = result
        self.resultChanged.emit(result)
        directory = output.parent if output is not None else fallback_directory
        if directory is not None:
            self.set_directory(str(Path(directory).resolve()))

        potential_error = None
        if potential is not None and potential.is_file():
            try:
                resolved_potential = potential.resolve()
                atoms = Potential.from_file(str(resolved_potential)).atoms
                self.set_structure(
                    atoms,
                    potential_path=str(resolved_potential),
                )
            except Exception as exc:  # noqa: BLE001 - backend reader boundary
                potential_error = exc
        return ResultAdoption(output, potential, potential_error)

    def reset(self) -> None:
        """Clear the document before publishing its cleared facets."""
        self.workspace.reset()
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)
        self.resultChanged.emit(None)

    def restart_scf(self) -> None:
        """Mark the attached potential for a fresh SCF cycle."""
        if self.workspace.atoms is None:
            raise ValueError("No structure is loaded.")
        self.workspace.atoms.potential.SCF_INFO.SCFSTATUS = "START"
        self.structureChanged.emit(self.workspace.atoms)
