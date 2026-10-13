"""Semantic transitions over the mutable calculation draft and result tree."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.result_store import ResultRecord, ResultStore
from guy4ase.gui.application.workspace import EmptySpheresState, Generation, WorkspaceState

_KEEP_DIRECTORY = object()


def _result_is_scf(result: Any) -> bool:
    try:
        return str(result.task_name).strip().lower() == "scf"
    except (AttributeError, TypeError, ValueError):
        return False


def _atoms_has_potential(atoms: Any) -> bool:
    """Return whether the authoritative atoms state owns a potential."""
    checker = getattr(atoms, "has_potential", None)
    return bool(callable(checker) and checker())


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive draft command."""

    APPLIED = auto()
    STALE = auto()


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable provenance captured when a calculation is launched.

    ``generation`` protects preparation against delayed draft callbacks.
    Completed calculations are always recorded against ``structure_id`` and
    ``state_id``. An SCF output may advance the workspace only while that exact
    input state is still active.

    ``atoms`` intentionally shares the workspace/result-store instance.  SPR-KKR
    preparation may lazily promote or populate caches/site/potential bookkeeping
    on that object; those mutations do not change the represented physical
    structure and therefore do not constitute a provenance or generation change.
    Structural edits must still go through controller transitions. ``atoms`` is
    also the sole physical authority for the input potential; potential paths
    are provenance/artifact metadata only.
    """

    atoms: Any
    input_parameters: Any
    directory: str
    generation: Generation
    structure_id: int
    state_id: int


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
    """Own the next-calculation draft and an independent result tree."""

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
        self._generation = self._workspace.generation
        self._results = ResultStore()
        if self._workspace.atoms is not None:
            structure_id, state_id = self._results.new_structure_state(
                self._workspace.atoms,
                potential_path=self._workspace.potential_path,
                empty_spheres=self._workspace.empty_spheres,
            )
            self._workspace.structure_id = structure_id
            self._workspace.state_id = state_id

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
        record = self._results.latest_result_for_state(self.state_id)
        return record.result if record is not None else None

    @property
    def result_history(self) -> tuple[ResultRecord, ...]:
        """Compatibility view; presentation should use ``result_store``."""
        return self._results.results

    @property
    def result_store(self) -> ResultStore:
        return self._results

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

    def can_calculate(self) -> bool:
        return self._workspace.can_calculate()

    def can_build_2d(self) -> bool:
        return self.structure_kind() == "3d"

    def scf_status(self) -> str | None:
        return self._workspace.scf_status()

    def is_scf_converged(self) -> bool:
        return self._workspace.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self._workspace.has_vacuum_sites()

    def empty_spheres_action(self) -> str | None:
        return self._workspace.empty_spheres_action()

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

    def _install_new_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
    ) -> None:
        structure_id, state_id = self._results.new_structure_state(
            atoms,
            potential_path=potential_path,
            empty_spheres=self._workspace.empty_spheres,
        )
        self._workspace.structure_id = structure_id
        self._workspace.state_id = state_id

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
        self._workspace.atoms = atoms
        self._workspace.potential_path = potential_path
        self._workspace.empty_spheres = None
        self._workspace.restarted = restarted
        self._install_new_structure_state(atoms, potential_path=potential_path)
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

        self._workspace.atoms = atoms
        self._workspace.restarted = True
        self._workspace.potential_path = None
        self._workspace.empty_spheres = None
        self._install_new_structure_state(atoms, potential_path=None)
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

    def adopt_external_result(self, loaded: LoadedResult) -> ResultAdoption:
        """Record an imported result without implicitly replacing the draft."""
        produces_state = loaded.atoms is not None and _result_is_scf(loaded.result)
        record = self._results.add_external_result(
            loaded.result,
            atoms=loaded.atoms,
            input_parameters=loaded.input_parameters,
            directory=loaded.directory,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            produces_state=produces_state,
        )
        self.resultChanged.emit(loaded.result)
        return self._result_adoption(loaded, record=record)

    def adopt_calculation_result(
        self,
        loaded: LoadedResult,
        *,
        request: CalculationRequest | None = None,
    ) -> ResultAdoption:
        """Always record a result; fast-forward only the exact active SCF input.

        A state selected by the user, including ``Use for New Calculation``, is
        a write barrier. Results finishing from an older state remain in their
        original branch and can become active only through an explicit action.
        """
        if request is None:
            if self.structure_id is None or self.state_id is None:
                record = self._results.add_external_result(
                    loaded.result,
                    atoms=loaded.atoms,
                    input_parameters=loaded.input_parameters,
                    directory=loaded.directory,
                    output_path=loaded.output_path,
                    potential_path=loaded.potential_path,
                    produces_state=(loaded.atoms is not None and _result_is_scf(loaded.result)),
                )
                self.resultChanged.emit(loaded.result)
                return self._result_adoption(loaded, record=record)
            request = CalculationRequest(
                atoms=self.atoms,
                input_parameters=loaded.input_parameters,
                directory=loaded.directory or self.directory or "",
                generation=self.generation,
                structure_id=self.structure_id,
                state_id=self.state_id,
            )

        is_scf = _result_is_scf(loaded.result)
        output_atoms = loaded.atoms if is_scf and loaded.atoms is not None else None
        record = self._results.add_result(
            loaded.result,
            structure_id=request.structure_id,
            input_state_id=request.state_id,
            atoms=request.atoms,
            input_parameters=request.input_parameters,
            directory=request.directory,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            output_atoms=output_atoms,
            output_potential_path=(
                str(loaded.potential_path)
                if loaded.potential_path is not None
                else None
            ),
        )

        workspace_updated = False
        if (
            is_scf
            and record.output_state_id is not None
            and request.structure_id == self._workspace.structure_id
            and request.state_id == self._workspace.state_id
        ):
            state = self._results.state(record.output_state_id)
            self._workspace.atoms = state.atoms
            self._workspace.potential_path = state.potential_path
            self._workspace.empty_spheres = state.empty_spheres
            self._workspace.state_id = state.id
            self._workspace.restarted = False
            self._changed()
            workspace_updated = True
            self.structureChanged.emit(state.atoms)

        self.resultChanged.emit(loaded.result)
        return self._result_adoption(
            loaded,
            record=record,
            workspace_updated=workspace_updated,
        )

    def use_result_state(self, result_id: int) -> None:
        """Explicitly activate the structure/potential represented by a result."""
        record = self._results.result(result_id)
        state_id = record.output_state_id or record.input_state_id
        if state_id is None:
            raise ValueError("The selected result has no reusable calculation input.")
        state = self._results.state(state_id)
        self._workspace.atoms = state.atoms
        self._workspace.potential_path = state.potential_path
        self._workspace.structure_id = state.structure_id
        self._workspace.state_id = state.id
        self._workspace.empty_spheres = state.empty_spheres
        self._workspace.restarted = (
            state.parent_id is not None and not _atoms_has_potential(state.atoms)
        )
        self._changed()
        self.structureChanged.emit(state.atoms)

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
        self._workspace.state_id = self._results.new_child_state(
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
        record = self._results.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            atoms=source,
            input_parameters=empty_spheres.parameters,
            directory=self.directory,
            output_atoms=updated if structure_changed else None,
            output_potential_path=(None if structure_changed else self.potential_path),
            output_empty_spheres=empty_spheres,
        )

        assert record.output_state_id is not None
        state = self._results.state(record.output_state_id)
        self._workspace.atoms = state.atoms
        self._workspace.potential_path = state.potential_path
        self._workspace.empty_spheres = state.empty_spheres
        self._workspace.state_id = state.id
        if structure_changed:
            self._workspace.restarted = True
        self._changed()
        if structure_changed:
            self.structureChanged.emit(state.atoms)

        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
