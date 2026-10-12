"""Semantic transitions over the mutable calculation draft and result history."""
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


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive draft command."""

    APPLIED = auto()
    STALE = auto()


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable provenance captured when a calculation is launched.

    ``generation`` protects preparation against delayed draft callbacks. Result
    adoption instead uses ``structure_id``/``state_id``: every completed result
    is recorded, while an SCF result may advance the active workspace potential
    only when it was launched from the potential which is still active.
    """

    atoms: Any
    input_parameters: Any
    directory: str
    generation: Generation
    structure_id: int = 0
    state_id: int = 0


@dataclass(frozen=True)
class ResultAdoption:
    """Outcome of recording a completed calculation result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None
    input_parameters_error: Exception | None = None
    adopted: bool = True
    workspace_updated: bool = False
    record: ResultRecord | None = None


class WorkspaceController(QObject):
    """Own the next-calculation draft and an independent result provenance store."""

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
        return self._workspace.potential_path

    @property
    def structure_id(self) -> int | None:
        return self._workspace.structure_id

    @property
    def state_id(self) -> int | None:
        return self._workspace.state_id

    @property
    def result(self) -> Any | None:
        """Return the most recently recorded result (compatibility read API)."""
        history = self.result_history
        return history[0].result if history else None

    @property
    def result_history(self) -> tuple[ResultRecord, ...]:
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
        self._generation = self._generation.next_major()
        self._workspace.generation = self._generation

    def _set_directory(self, directory: Any) -> bool:
        if directory is _KEEP_DIRECTORY or directory == self._workspace.directory:
            return False
        self._workspace.directory = directory
        return True

    def _state_still_uses_source_potential(self, source_state_id: int) -> bool:
        """Return whether the active state still uses ``source_state_id``'s potential.

        ``Use for New Calculation`` creates a bookkeeping child so a new SCF
        sequence can be shown as a separate branch, but it deliberately keeps
        the same starting potential. Such restart-only children therefore do
        not prevent an already running SCF from fast-forwarding the workspace.
        Any state produced by an actual result (SCF, Empty Spheres, ...) is a
        real change and stops the walk.
        """
        current_id = self._workspace.state_id
        while current_id is not None:
            if current_id == source_state_id:
                return True
            current = self._results.state(current_id)
            if current.produced_by_result_id is not None:
                return False
            current_id = current.parent_id
        return False

    def _install_new_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
    ) -> None:
        structure_id, state_id = self._results.new_structure_state(
            atoms,
            potential_path=potential_path,
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
            adopted=True,
            workspace_updated=workspace_updated,
            record=record,
        )

    def adopt_external_result(
        self,
        loaded: LoadedResult,
        *,
        expected_generation: Generation | None = None,
    ) -> ResultAdoption:
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
        expected_major: int | None = None,
    ) -> ResultAdoption:
        """Always record a result; conditionally advance the active SCF state.

        For SCF, ``pot_new``/loaded atoms become the workspace starting point
        exactly when the calculation was launched from the potential which is
        still active. Sibling or late SCF results form independent history
        branches and never roll the workspace back. Non-SCF results never
        mutate the active workspace state.
        """
        if request is None:
            if self.structure_id is None or self.state_id is None:
                if loaded.atoms is not None:
                    self._install_new_structure_state(
                        loaded.atoms,
                        potential_path=(
                            str(loaded.potential_path)
                            if loaded.potential_path is not None
                            else None
                        ),
                    )
                else:
                    record = self._results.add_external_result(
                        loaded.result,
                        atoms=None,
                        input_parameters=loaded.input_parameters,
                        directory=loaded.directory,
                        output_path=loaded.output_path,
                        potential_path=loaded.potential_path,
                        produces_state=False,
                    )
                    self.resultChanged.emit(loaded.result)
                    return self._result_adoption(loaded, record=record)
            assert self.structure_id is not None and self.state_id is not None
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
            and self._state_still_uses_source_potential(request.state_id)
        ):
            state = self._results.state(record.output_state_id)
            self._workspace.atoms = state.atoms
            self._workspace.potential_path = state.potential_path
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

    def use_result_structure(self, result_id: int) -> None:
        """Explicitly copy a historical result's state into the draft."""
        record = self._results.result(result_id)
        state_id = record.output_state_id or record.input_state_id
        if state_id is None:
            raise ValueError("The selected result has no reusable structure state.")
        state = self._results.state(state_id)
        self._workspace.atoms = state.atoms
        self._workspace.potential_path = state.potential_path
        self._workspace.structure_id = state.structure_id
        self._workspace.state_id = state.id
        self._workspace.empty_spheres = None
        self._workspace.restarted = False
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
        self._workspace.state_id = self._results.new_child_state(state_id)
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
        self._workspace.empty_spheres = empty_spheres
        record = self._results.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            atoms=source,
            input_parameters=empty_spheres.parameters,
            directory=self.directory,
            output_atoms=updated if structure_changed else None,
            output_potential_path=None,
        )

        if structure_changed:
            assert record.output_state_id is not None
            self._workspace.atoms = updated
            self._workspace.potential_path = None
            self._workspace.state_id = record.output_state_id
            self._workspace.restarted = True
        self._changed()

        self.structureChanged.emit(updated if structure_changed else source)
        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
