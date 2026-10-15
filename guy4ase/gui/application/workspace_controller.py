"""Semantic transitions over the mutable calculation state and result tree."""
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
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.result_store import ResultRecord, ResultStore
from guy4ase.gui.application.workspace import EmptySpheresState, Generation, WorkspaceState
from guy4ase.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction

_KEEP_DIRECTORY = object()


def _atoms_has_potential(atoms: Any) -> bool:
    """Return whether the authoritative atoms state owns a potential."""
    checker = getattr(atoms, "has_potential", None)
    return bool(callable(checker) and checker())


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive calculation-state command."""

    APPLIED = auto()
    STALE = auto()


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable provenance captured when a calculation is launched.

    ``generation`` protects preparation against delayed state callbacks.
    Completed calculations are always recorded against ``structure_id`` and
    ``state_id``. A potential-producing output may advance the calculation state
    only while that exact input state is still active.

    ``atoms`` identifies the authoritative launch input and is the sole physical
    authority for its potential; potential paths are provenance/artifact metadata
    only. The request may still reference the workspace object, but the execution
    service copies it before ASE2SPRKKR sees it. Lazy promotion, site
    initialization and backend bookkeeping therefore affect only the execution
    copy. Structural edits remain controller transitions.

    ``restart_scf`` snapshots the pending workspace execution intent. It asks
    ASE2SPRKKR to serialize ``SCFSTATUS START`` for this run without mutating the
    authoritative workspace potential. ``project_id`` snapshots launch
    attribution so later project selection cannot move the run.
    """

    atoms: Atoms
    input_parameters: Any
    directory: str
    generation: Generation
    structure_id: int
    state_id: int
    restart_scf: bool = False
    project_id: str | None = None


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
    """Own calculation state, launch context, and an independent result tree."""

    structureChanged = pyqtSignal(object)
    inputParametersChanged = pyqtSignal(object)
    directoryChanged = pyqtSignal(object)
    activeProjectChanged = pyqtSignal(object)
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
        self._results = ResultStore()
        calculation = self._workspace.calculation
        if calculation.atoms is not None:
            structure_id, state_id = self._results.new_structure_state(
                calculation.atoms,
                potential_path=calculation.potential_path,
                empty_spheres=calculation.empty_spheres,
            )
            calculation.structure_id = structure_id
            calculation.state_id = state_id

    @property
    def atoms(self) -> Any:
        return self._workspace.calculation.atoms

    @property
    def input_parameters(self) -> Any:
        return self._workspace.calculation.input_parameters

    @property
    def directory(self) -> str | None:
        return self._workspace.context.directory

    @property
    def active_project_id(self) -> str | None:
        return self._workspace.context.active_project_id

    @property
    def potential_path(self) -> str | None:
        """Return potential provenance/artifact path, never calculation input."""
        return self._workspace.calculation.potential_path

    @property
    def structure_id(self) -> int | None:
        return self._workspace.calculation.structure_id

    @property
    def state_id(self) -> int | None:
        return self._workspace.calculation.state_id

    @property
    def result(self) -> Any | None:
        """Return the latest result attached to the active calculation state."""
        record = self._results.latest_result_for_state(self.state_id)
        return record.result if record is not None else None

    @property
    def result_store(self) -> ResultStore:
        return self._results

    @property
    def empty_spheres(self) -> EmptySpheresState | None:
        return self._workspace.calculation.empty_spheres

    @property
    def empty_spheres_added(self) -> int | None:
        state = self.empty_spheres
        return None if state is None else state.count

    @property
    def restarted(self) -> bool:
        return self._workspace.calculation.restarted

    @property
    def generation(self) -> Generation:
        return self._generation

    def structure_kind(self):
        return self._workspace.calculation.structure_kind()

    def can_calculate(self) -> bool:
        """Return generic launch readiness, independent of Guided workflow policy."""
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def can_build_2d(self) -> bool:
        return self.structure_kind() == "3d"

    def scf_status(self) -> str | None:
        return self._workspace.calculation.scf_status()

    def is_scf_converged(self) -> bool:
        return self._workspace.calculation.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self._workspace.calculation.has_vacuum_sites()

    def empty_spheres_action(self) -> _EmptySpheresAction | None:
        """Return the empty-sphere workflow action recommended for the state."""
        if self.atoms is None:
            return None
        if self.empty_spheres is not None:
            return _EmptySpheresAction.RECALCULATE
        if self.has_vacuum_sites():
            return None
        return _EmptySpheresAction.ADD

    def structure_change_requires_scf_restart(self) -> bool:
        if self.atoms is None or self.restarted:
            return False
        if self.is_scf_converged():
            return True
        return self.scf_status() not in (None, "START")

    def create_calculation_request(self) -> CalculationRequest:
        atoms = self.atoms
        parameters = self.input_parameters
        directory = self.directory
        structure_id = self.structure_id
        state_id = self.state_id
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
            project_id=self.active_project_id,
        )

    def _generation_is_current(self, expected: Generation | None) -> bool:
        return expected is None or expected == self._generation

    def _changed(self) -> None:
        self._generation = self._generation.next()
        self._workspace.generation = self._generation

    def _set_directory(self, directory: Any) -> bool:
        context = self._workspace.context
        if directory is _KEEP_DIRECTORY or directory == context.directory:
            return False
        context.directory = directory
        return True

    def set_active_project(self, project_id: str | None) -> None:
        """Set launch attribution without invalidating calculation-state edits."""
        project_id = None if project_id is None else str(project_id)
        context = self._workspace.context
        if project_id == context.active_project_id:
            return
        context.active_project_id = project_id
        self.activeProjectChanged.emit(project_id)

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
        if atoms is None:
            structure_id = state_id = None
        else:
            structure_id, state_id = self._results.new_structure_state(
                atoms,
                potential_path=potential_path,
                empty_spheres=None,
            )
        calculation = self._workspace.calculation
        calculation.atoms = atoms
        calculation.potential_path = potential_path
        calculation.structure_id = structure_id
        calculation.state_id = state_id
        calculation.empty_spheres = None
        calculation.restarted = restarted
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

        structure_id, state_id = self._results.new_structure_state(
            atoms,
            potential_path=None,
            empty_spheres=None,
        )
        calculation = self._workspace.calculation
        calculation.atoms = atoms
        calculation.potential_path = None
        calculation.structure_id = structure_id
        calculation.state_id = state_id
        calculation.empty_spheres = None
        calculation.restarted = True
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
        self._workspace.calculation.input_parameters = parameters
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
        """Record an imported result without implicitly replacing the state.

        ``select_result`` carries explicit presentation intent from a user-driven
        import. Background/programmatic imports leave the current result selection
        untouched.
        """
        record = self._results.add_external_result(
            loaded.result,
            atoms=loaded.atoms,
            input_parameters=loaded.input_parameters,
            directory=loaded.directory,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
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
        """Record a launched result against its exact captured provenance.

        A state selected by the user, including ``Use for New Calculation``, is
        a write barrier. Results finishing from an older state remain in their
        original branch and can become active only through an explicit action.
        """
        produces_potential = loaded.result.produces_potential
        output_atoms = (
            loaded.atoms
            if produces_potential and loaded.atoms is not None
            else None
        )
        output_potential_path = (
            str(loaded.potential_path)
            if produces_potential and loaded.potential_path is not None
            else None
        )
        record = self._results.add_result(
            loaded.result,
            structure_id=request.structure_id,
            input_state_id=request.state_id,
            input_parameters=request.input_parameters,
            directory=request.directory,
            persistent_ref=loaded.persistent_ref,
            restart_scf=request.restart_scf,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            output_atoms=output_atoms,
            output_potential_path=output_potential_path,
        )

        workspace_updated = False
        calculation = self._workspace.calculation
        if (
            produces_potential
            and output_atoms is not None
            and record.output_state_id is not None
            and request.structure_id == calculation.structure_id
            and request.state_id == calculation.state_id
        ):
            state = self._results.state(record.output_state_id)
            calculation.atoms = output_atoms
            calculation.potential_path = state.potential_path
            calculation.empty_spheres = state.empty_spheres
            calculation.state_id = state.id
            calculation.restarted = False
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
            self._results,
            result_id,
            active_state_id=self.state_id,
            expected_potential=expected_potential,
        )
        if isinstance(resolution, HistoricalStateAlreadyActive):
            return

        atoms = resolution.atoms
        if isinstance(resolution, NewHistoricalPotential):
            target_state_id = self._results.new_child_state(
                resolution.parent_state.id,
                potential_path=str(resolution.potential_version.path),
                potential_version=resolution.potential_version,
                empty_spheres=None,
            )
            target_state = self._results.state(target_state_id)
        else:
            target_state = resolution.state

        calculation = self._workspace.calculation
        calculation.atoms = atoms
        calculation.potential_path = target_state.potential_path
        calculation.structure_id = target_state.structure_id
        calculation.state_id = target_state.id
        calculation.empty_spheres = target_state.empty_spheres
        calculation.restarted = (
            target_state.parent_id is not None and not _atoms_has_potential(atoms)
        )
        self._changed()
        self.structureChanged.emit(atoms)

    def reset(self) -> None:
        """Clear calculation state while preserving history and project selection."""
        calculation = self._workspace.calculation
        calculation.atoms = None
        calculation.potential_path = None
        calculation.input_parameters = None
        calculation.structure_id = None
        calculation.state_id = None
        calculation.empty_spheres = None
        calculation.restarted = False
        self._set_directory(None)
        self._changed()
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)

    def use_for_new_calculation(
        self,
        *,
        result_id: int | None = None,
        expected_potential: PotentialFileVersion | None = None,
        expected_generation: Generation | None = None,
    ) -> DocumentChange:
        """Create one new calculation branch from active or historical state.

        Historical restoration and branch creation are one observable workspace
        transition: all filesystem-dependent reconstruction is completed before
        provenance or workspace state is mutated, then exactly one branch state is
        committed and published.
        """
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        child_kwargs: dict[str, Any] = {}
        if result_id is None:
            atoms = self.atoms
            parent_state_id = self.state_id
        else:
            resolution = resolve_historical_state(
                self._results,
                result_id,
                active_state_id=self.state_id,
                expected_potential=expected_potential,
            )
            if not self._generation_is_current(expected_generation):
                return DocumentChange.STALE

            if isinstance(resolution, HistoricalStateAlreadyActive):
                atoms = self.atoms
                parent_state_id = self.state_id
            elif isinstance(resolution, NewHistoricalPotential):
                atoms = resolution.atoms
                parent_state_id = resolution.parent_state.id
                child_kwargs = {
                    "potential_path": str(resolution.potential_version.path),
                    "potential_version": resolution.potential_version,
                    "empty_spheres": None,
                }
            else:
                atoms = resolution.atoms
                parent_state_id = resolution.state.id

        if atoms is None or parent_state_id is None:
            raise ValueError("No calculation state is available for a new branch.")

        state_id = self._results.new_child_state(
            parent_state_id,
            new_branch=True,
            **child_kwargs,
        )
        state = self._results.state(state_id)
        calculation = self._workspace.calculation
        calculation.atoms = atoms
        calculation.potential_path = state.potential_path
        calculation.structure_id = state.structure_id
        calculation.state_id = state.id
        calculation.empty_spheres = state.empty_spheres
        calculation.restarted = True
        self._changed()
        self.structureChanged.emit(atoms)
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

        previous_state = self.empty_spheres
        previous_count = previous_state.count if previous_state is not None else 0
        updated, count, structure_changed = edit(source.copy(), previous_count)
        if not self._generation_is_current(expected_generation):
            return DocumentChange.STALE

        empty_spheres = EmptySpheresState(count=count, parameters=parameters or {})
        result = EmptySpheresResult(found=empty_spheres.count)
        record = self._results.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            input_parameters=empty_spheres.parameters,
            directory=self.directory,
            output_atoms=updated if structure_changed else None,
            output_potential_path=(None if structure_changed else self.potential_path),
            output_empty_spheres=empty_spheres,
        )

        assert record.output_state_id is not None
        state = self._results.state(record.output_state_id)
        active_atoms = updated if structure_changed else source
        calculation = self._workspace.calculation
        calculation.atoms = active_atoms
        calculation.potential_path = state.potential_path
        calculation.empty_spheres = state.empty_spheres
        calculation.state_id = state.id
        if structure_changed:
            calculation.restarted = True
        self._changed()
        if structure_changed:
            self.structureChanged.emit(active_atoms)

        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
