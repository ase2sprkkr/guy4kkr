"""Application operations over the shared workspace document."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.workspace import WorkspaceState


@dataclass(frozen=True)
class ResultArtifacts:
    """Paths discovered while adopting a calculation result."""

    output_path: Path | None = None
    potential_path: Path | None = None


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
        if resolved.is_absolute():
            return resolved
        base = getattr(result, "directory", None) or fallback_directory
        return Path(base) / resolved if base else resolved

    def adopt_result(
        self,
        result: Any,
        *,
        fallback_directory: str | Path | None = None,
    ) -> ResultArtifacts:
        """Adopt a result and resolve its document-level output artifacts."""
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
        return ResultArtifacts(output, potential)

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
