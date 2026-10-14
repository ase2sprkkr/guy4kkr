"""Semantic transitions over the mutable calculation draft and result history."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from ase import Atoms
from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.historical_state import (
    HistoricalStateAlreadyActive,
    NewHistoricalPotential,
    resolve_historical_state,
)
from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_artifacts import find_existing_external_result
from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory, ResultRecord
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import EmptySpheresState, Generation, WorkspaceState

_KEEP_DIRECTORY = object()
_POST_SCF_TASKS = frozenset({"xas", "arpes", "dos", "bsf", "jxc"})


def _atoms_has_potential(atoms: Any) -> bool:
    """Return whether the authoritative atoms state owns a potential."""
    checker = getattr(atoms, "has_potential", None)
    return bool(callable(checker) and checker())


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive draft command."""

    APPLIED = auto()
    STALE = auto()


class EmptySpheresAction(Enum):
    """Recommended empty-sphere action for the current workspace draft."""

    ADD = auto()
    RECALCULATE = auto()


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable provenance captured when a calculation is launched.

    ``generation`` protects preparation against delayed draft callbacks.
    Completed calculations are always recorded against ``structure_id`` and
    ``state_id``. An SCF output may advance the workspace only while that exact
    input state is still active.

    ``atoms`` identifies the authoritative launch input and is the sole physical
    authority for its potential; potential paths are provenance/artifact metadata
    only. The execution service copies it before ASE2SPRKKR sees it.

    ``restart_scf`` snapshots the pending workspace execution intent.
    """

    atoms: Atoms
    input_parameters: Any
    directory: str
    generation: Generation
    structure_id: int
    state_id: int
    restart_scf: bool = False


@dataclass(frozen=True)
class ResultAdoption:
    """Artifacts and workspace effect of recording a completed result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None
    input_parameters_error: Exception | None = None
    workspace_updated: bool = False
    record: ResultRecord | None = None


class WorkspaceController(QObject):
    """Own the next-calculation draft and an independent result history."""

    structureChanged = pyqtSignal(object)
    inputParametersChanged = pyqtSignal(object)
    directoryChanged = pyqtSignal(object)
    resultChanged = pyqtSignal(object)
    resultSelectionRequested = pyqtSignal(int)

    def __init__(
        self,
        workspace: WorkspaceState | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace or WorkspaceState()
        self._generation = self._workspace.generation
        self._history = ResultHistory()
        if self._workspace.atoms is not None:
            captured = capture_structure(
                self._workspace.atoms,
                potential_path=self._workspace.potential_path,
            )
            structure_id, state_id = self._history.add_structure_state(
                captured,
                empty_spheres=self._workspace.empty_spheres,
            )
            self._workspace.structure_id = structure_id
            self._workspace.state_id = state_id
            self._workspace.potential_path = (
                str(captured.potential_path)
                if captured.potential_path is not None
                else None
            )

    @property
    def atoms(self) -> Any:
        return self._workspace.atoms

    @property
    def input_parameters(self) -> Any:
        return self._workspace.input_parameters

    @property
    def directory(self) -> str | None:
        return self._workspace.directory

    @property
    def potential_path(self) -> str | None:
        """Return potential provenance/artifact path, never calculation input."""
        return self._workspace.potential_path

    @property
    def structure_id(self) -> int | None:
        return self._workspace.structure_id

    @property
    def state_id(self) -> int | None:
        return self._workspace.state_id

    @property
    def result(self) -> Any | None:
        """Return the latest result attached to the active workspace state."""
        record = self._history.latest_result_for_state(self.state_id)
        return record.result if record is not None else None

    @property
    def result_history(self) -> ResultHistory:
        return self._history

    @property
    def empty_spheres(self) -> EmptySpheresState | None:
        return self._workspace.empty_spheres

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

    def current_task(self) -> str | None:
        """Return the normalized task of the active input parameters, if known."""
        parameters = self.input_parameters
        try:
            task = str(parameters.task_name).strip().lower()
        except (AttributeError, TypeError, ValueError):
            return None
        return task or None

    def can_calculate(self) -> bool:
        if not self._workspace.is_calculation_input_complete():
            return False
        task = self.current_task()
        return task is None or self.can_run_task(task)

    def can_run_task(self, task: str) -> bool:
        """Return whether the active workspace satisfies ``task`` prerequisites."""
        if self.atoms is None:
            return False
        task = str(task).strip().lower()
        if task == "scf":
            return True
        if task in _POST_SCF_TASKS:
            return self.is_scf_converged()
        return False

    def can_build_2d(self) -> bool:
        return self.structure_kind() == "3d"

    def scf_status(self) -> str | None:
        return self._workspace.scf_status()

    def is_scf_converged(self) -> bool:
        return self._workspace.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self._workspace.has_vacuum_sites()

    def empty_spheres_action(self) -> EmptySpheresAction | None:
        """Return the empty-sphere workflow action recommended for the draft."""
        if self.atoms is None:
            return None
        if self.empty_spheres is not None:
            return EmptySpheresAction.RECALCULATE
        if self.has_vacuum_sites():
            return None
        return EmptySpheresAction.ADD

    def structure_change_requires_scf_restart(self) -> bool:
        if self.atoms is None or self.restarted:
            return False
        if self.is_scf_converged():
            return True
        return self.scf_status() not in (None, "START")

    def create_calculation_request(self) -> CalculationRequest:
        atoms = self.atoms
        parameters = self.input_parameters
        directory = self._workspace.directory
        structure_id = self._workspace.structure_id
        state_id = self._workspace.state_id
        if (
            atoms is None
            or parameters is None
            or not directory
            or structure_id is None
            or state_id is None
        ):
            raise CalculationNotReady(
                "Structure, input parameters, working directory and calculation state are required."
            )
        return CalculationRequest(
            atoms=atoms,
            input_parameters=parameters.copy(copy_values=True),
            directory=directory,
            generation=self._generation,
            structure_id=structure_id,
            state_id=state_id,
            restart_scf=self.restarted,
        )

    def _generation_is_current(self, expected: Generation | None) -> bool:
        return expected is None or expected == self._generation

    def _changed(self) -> None:
        self._generation = self._generation.next()
        self._workspace.generation = self._generation

    def _set_directory(self, directory: Any) -> bool:
        if directory is _KEEP_DIRECTORY or directory == self._workspace.directory:
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
        captured = capture_structure(atoms, potential_path=potential_path)
        structure_id, state_id = self._history.add_structure_state(captured)
        self._workspace.atoms = atoms
        self._workspace.potential_path = (
            str(captured.potential_path) if captured.potential_path is not None else None
        )
        self._workspace.structure_id = structure_id
        self._workspace.state_id = state_id
        self._workspace.empty_spheres = None
        self._workspace.restarted = restarted
        directory_changed = self._set_directory(directory)
        self._changed()
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

        captured = capture_structure(atoms, potential_path=None)
        structure_id, state_id = self._history.add_structure_state(captured)
        self._workspace.atoms = atoms
        self._workspace.potential_path = None
        self._workspace.structure_id = structure_id
        self._workspace.state_id = state_id
        self._workspace.empty_spheres = None
        self._workspace.restarted = True
        self._changed()
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
        directory_changed = self._set_directory(directory)
        self._workspace.input_parameters = parameters
        self._changed()
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return DocumentChange.APPLIED

    def change_directory(self, directory: str | None) -> None:
        if not self._set_directory(directory):
            return
        self._changed()
        self.directoryChanged.emit(directory)

    @staticmethod
    def _result_adoption(
        loaded: LoadedResult,
        *,
        record: ResultRecord | None = None,
        workspace_updated: bool = False,
    ) -> ResultAdoption:
        return ResultAdoption(
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            potential_error=loaded.potential_error,
            input_parameters_error=loaded.input_parameters_error,
            workspace_updated=workspace_updated,
            record=record,
        )

    def adopt_external_result(
        self,
        loaded: LoadedResult,
        *,
        select_result: bool = False,
    ) -> ResultAdoption:
        """Record an imported result without implicitly replacing the draft."""
        record = find_existing_external_result(
            self._history,
            loaded.output_path,
            persistent_ref=loaded.persistent_ref,
        )
        if record is None:
            captured = capture_result(
                loaded.result,
                input_parameters=loaded.input_parameters,
                output_path=loaded.output_path,
                potential_path=loaded.potential_path,
            )
            structure = (
                capture_structure(
                    loaded.atoms,
                    potential_path=loaded.potential_path,
                    potential_version=loaded.potential_version,
                )
                if loaded.atoms is not None
                else None
            )
            record = self._history.add_external_result(
                captured,
                structure=structure,
                directory=loaded.directory,
                produces_state=(loaded.atoms is not None and captured.task_name == "scf"),
                persistent_ref=loaded.persistent_ref,
            )

        self.resultChanged.emit(loaded.result)
        if select_result:
            self.resultSelectionRequested.emit(record.id)
        return self._result_adoption(loaded, record=record)

    def adopt_calculation_result(
        self,
        loaded: LoadedResult,
        *,
        request: CalculationRequest,
    ) -> ResultAdoption:
        """Record a launched result against its exact captured provenance."""
        captured = capture_result(
            loaded.result,
            input_parameters=request.input_parameters,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
        )
        is_scf = captured.task_name == "scf"
        output_atoms = loaded.atoms if is_scf and loaded.atoms is not None else None
        output_structure = (
            capture_structure(
                output_atoms,
                potential_path=loaded.potential_path,
                potential_version=loaded.potential_version,
            )
            if output_atoms is not None
            else None
        )

        record = self._history.add_result(
            captured,
            structure_id=request.structure_id,
            input_state_id=request.state_id,
            directory=request.directory,
            persistent_ref=loaded.persistent_ref,
            restart_scf=request.restart_scf,
            output_structure=output_structure,
        )

        workspace_updated = False
        if (
            is_scf
            and output_atoms is not None
            and record.output_state_id is not None
            and request.structure_id == self._workspace.structure_id
            and request.state_id == self._workspace.state_id
        ):
            state = self._history.state(record.output_state_id)
            self._workspace.atoms = output_atoms
            self._workspace.potential_path = (
                str(state.potential_path) if state.potential_path is not None else None
            )
            self._workspace.empty_spheres = state.empty_spheres
            self._workspace.state_id = state.id
            self._workspace.restarted = False
            self._changed()
            workspace_updated = True
            self.structureChanged.emit(output_atoms)

        self.resultChanged.emit(loaded.result)
        return self._result_adoption(
            loaded,
            record=record,
            workspace_updated=workspace_updated,
        )

    def use_result_state(
        self,
        result_id: int,
        expected_potential: PotentialFileVersion | None = None,
    ) -> None:
        """Activate a reconstructable historical state or approved current POTFIL."""
        resolution = resolve_historical_state(
            self._history,
            result_id,
            active_state_id=self.state_id,
            expected_potential=expected_potential,
        )
        if isinstance(resolution, HistoricalStateAlreadyActive):
            return

        atoms = resolution.atoms
        if isinstance(resolution, NewHistoricalPotential):
            captured = capture_structure(
                atoms,
                potential_path=resolution.potential_version.path,
                potential_version=resolution.potential_version,
            )
            target_state_id = self._history.add_child_state(
                resolution.parent_state.id,
                structure=captured,
                empty_spheres=None,
            )
            target_state = self._history.state(target_state_id)
        else:
            target_state = resolution.state

        self._workspace.atoms = atoms
        self._workspace.potential_path = (
            str(target_state.potential_path)
            if target_state.potential_path is not None
            else None
        )
        self._workspace.structure_id = target_state.structure_id
        self._workspace.state_id = target_state.id
        self._workspace.empty_spheres = target_state.empty_spheres
        self._workspace.restarted = (
            target_state.parent_id is not None and not _atoms_has_potential(atoms)
        )
        self._changed()
        self.structureChanged.emit(atoms)

    def reset(self) -> None:
        """Clear the draft while deliberately preserving calculation history."""
        self._workspace.atoms = None
        self._workspace.potential_path = None
        self._workspace.input_parameters = None
        self._workspace.structure_id = None
        self._workspace.state_id = None
        self._workspace.empty_spheres = None
        self._workspace.restarted = False
        self._set_directory(None)
        self._changed()
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)

    def use_for_new_calculation(
        self, *, expected_generation: Generation | None = None
    ) -> DocumentChange:
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE
        state_id = self._workspace.state_id
        if state_id is None:
            raise ValueError("No calculation state is active.")
        self._workspace.state_id = self._history.add_child_state(
            state_id,
            new_branch=True,
        )
        self._workspace.restarted = True
        self._changed()
        self.structureChanged.emit(self.atoms)
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
        structure_id = self.structure_id
        state_id = self.state_id
        if source is None or structure_id is None or state_id is None:
            raise ValueError("No structure is loaded.")

        previous_state = self._workspace.empty_spheres
        previous_count = previous_state.count if previous_state is not None else 0
        updated, count, structure_changed = edit(source.copy(), previous_count)
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        empty_spheres = EmptySpheresState(count=count, parameters=parameters or {})
        result = EmptySpheresResult(found=empty_spheres.count)
        captured = capture_result(
            result,
            input_parameters=empty_spheres.parameters,
            output_path=None,
            potential_path=None,
        )
        output_structure = (
            capture_structure(updated, potential_path=None)
            if structure_changed
            else None
        )

        record = self._history.add_result(
            captured,
            structure_id=structure_id,
            input_state_id=state_id,
            directory=self.directory,
            output_structure=output_structure,
            output_empty_spheres=empty_spheres,
        )

        assert record.output_state_id is not None
        state = self._history.state(record.output_state_id)
        active_atoms = updated if structure_changed else source
        self._workspace.atoms = active_atoms
        self._workspace.potential_path = (
            str(state.potential_path) if state.potential_path is not None else None
        )
        self._workspace.empty_spheres = state.empty_spheres
        self._workspace.state_id = state.id
        if structure_changed:
            self._workspace.restarted = True
        self._changed()
        if structure_changed:
            self.structureChanged.emit(active_atoms)

        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
