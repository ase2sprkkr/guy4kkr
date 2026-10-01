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

_KEEP_DIRECTORY = object()


@dataclass(frozen=True)
class ResultAdoption:
    """Artifacts and a non-fatal potential error from adopting a result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None


class WorkspaceController(QObject):
    """Own semantic document transitions and workspace consistency.

    This is not a bag of public attribute setters. Structure and calculation
    setup replacements invalidate stale results, transformed structures lose
    unrelated potential sources, and external results never retain atoms from
    an older document. The controller knows neither dialogs nor concrete views;
    file choosers and error presentation remain UI concerns.
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

    def _set_structure(
        self,
        atoms: Any,
        *,
        potential_path: str | None = None,
        force: bool = False,
    ) -> None:
        """Set structure facets and publish their shared presentation signal."""
        if (
            not force
            and self.workspace.atoms is atoms
            and self.workspace.potential_path == potential_path
        ):
            return
        self.workspace.atoms = atoms
        self.workspace.potential_path = potential_path
        self.structureChanged.emit(atoms)

    def _set_input_parameters(self, parameters: Any) -> None:
        if self.workspace.input_parameters is parameters:
            return
        self.workspace.input_parameters = parameters
        self.inputParametersChanged.emit(parameters)

    def _set_directory(self, directory: str | None) -> None:
        if self.workspace.directory == directory:
            return
        self.workspace.directory = directory
        self.directoryChanged.emit(directory)

    def _set_result(self, result: Any) -> None:
        if self.workspace.result is result:
            return
        self.workspace.result = result
        self.resultChanged.emit(result)

    def replace_structure(
        self,
        atoms: Any,
        *,
        potential_path: str | None = None,
    ) -> None:
        """Publish a user-selected or transformed structure.

        The previous calculation result and, by default, potential provenance
        no longer describe the replacement structure. Calculation setup and
        working directory remain useful and are preserved.
        """
        self._set_result(None)
        self._set_structure(atoms, potential_path=potential_path)

    def replace_input_parameters(
        self,
        parameters: Any,
        *,
        directory: Any = _KEEP_DIRECTORY,
    ) -> None:
        """Publish an explicitly changed calculation setup.

        Any current result belongs to the previous setup. The directory is
        preserved unless the caller explicitly supplies a new one.
        """
        self._set_result(None)
        if directory is not _KEEP_DIRECTORY:
            self._set_directory(directory)
        self._set_input_parameters(parameters)

    def change_working_directory(self, directory: str | None) -> None:
        """Select the directory used for subsequent document operations."""
        self._set_directory(directory)

    def load_structure(self, file_path: str | Path) -> Any:
        """Load a structure document and invalidate the previous result."""
        resolved = Path(file_path).resolve()
        atoms = ase_read(resolved)
        self._set_result(None)
        self._set_directory(str(resolved.parent))
        self._set_structure(
            atoms,
            potential_path=(
                str(resolved)
                if resolved.suffix.lower() in {".pot", ".pot_new"}
                else None
            ),
        )
        return atoms

    def load_input_parameters(self, file_path: str | Path) -> InputParameters:
        """Load calculation setup, its directory, and invalidate old results."""
        resolved = Path(file_path).resolve()
        parameters = InputParameters.from_file(resolved)
        self._set_result(None)
        self._set_directory(str(resolved.parent))
        self._set_input_parameters(parameters)
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
        """Load an external result without retaining unrelated old atoms.

        Unlike :meth:`adopt_calculation_result`, failure to read the result's
        potential clears the structure and its potential provenance. Existing
        input parameters remain an independent editable setup; they are not
        treated as provenance of the external result.
        """
        resolved = Path(file_path).resolve()
        result = TaskResult.from_file(resolved)
        output, potential = self._result_artifacts(result, resolved.parent)
        output = output or resolved
        atoms, potential_error = self._load_result_potential(potential)

        # Invalidate the old relationship before publishing any new facet.
        self._set_result(None)
        self._set_structure(
            atoms,
            potential_path=str(potential) if atoms is not None else None,
        )
        self._set_directory(str(output.parent.resolve()))
        self._set_result(result)
        return ResultAdoption(output, potential, potential_error)

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

    def _result_artifacts(
        self,
        result: Any,
        fallback_directory: str | Path | None,
    ) -> tuple[Path | None, Path | None]:
        """Resolve output and potential artifacts exposed by a result adapter."""
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
            potential,
            result,
            fallback_directory or self.workspace.directory,
        )
        return output, potential

    @staticmethod
    def _load_result_potential(
        potential: Path | None,
    ) -> tuple[Any | None, Exception | None]:
        """Read result atoms, returning backend failures as non-fatal data."""
        if potential is not None and potential.is_file():
            try:
                resolved_potential = potential.resolve()
                atoms = Potential.from_file(str(resolved_potential)).atoms
                return atoms, None
            except Exception as exc:  # noqa: BLE001 - backend reader boundary
                return None, exc
        return None, None

    def adopt_calculation_result(self, result: Any) -> ResultAdoption:
        """Adopt a result produced from the current workspace calculation.

        A readable converged potential replaces the structure. If it is absent
        or unreadable, current atoms and their provenance remain valid because
        this result was calculated from that workspace.
        """
        output, potential = self._result_artifacts(
            result,
            self.workspace.directory,
        )
        atoms, potential_error = self._load_result_potential(potential)

        self._set_result(None)
        if atoms is not None:
            self._set_structure(atoms, potential_path=str(potential.resolve()))
        directory = (
            output.parent
            if output is not None
            else getattr(result, "directory", None)
        )
        if directory is not None:
            self._set_directory(str(Path(directory).resolve()))
        self._set_result(result)
        return ResultAdoption(output, potential, potential_error)

    def reset(self) -> None:
        """Clear the document before publishing its cleared facets."""
        self._set_result(None)
        self._set_structure(None, potential_path=None)
        self._set_input_parameters(None)
        self._set_directory(None)

    def restart_scf(self) -> None:
        """Restart SCF state and invalidate the previous calculation result."""
        if self.workspace.atoms is None:
            raise ValueError("No structure is loaded.")
        self._set_result(None)
        self.workspace.atoms.potential.SCF_INFO.SCFSTATUS = "START"
        self._set_structure(
            self.workspace.atoms,
            potential_path=self.workspace.potential_path,
            force=True,
        )
