"""Semantic transitions over the mutable calculation draft and result tree."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_loading import LoadedResult, load_potential_atoms
from guy4ase.gui.application.result_store import (
    CalculationStateRecord,
    ResultRecord,
    ResultStore,
)
from guy4ase.gui.application.workspace import EmptySpheresState, Generation, WorkspaceState

_KEEP_DIRECTORY = object()
_POST_SCF_TASKS = frozenset({"xas", "arpes", "dos", "bsf", "jxc"})


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


class PotentialVersionChanged(RuntimeError):
    """The potential file no longer matches the version approved by the user."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable provenance captured when a calculation is launched.

    ``generation`` protects preparation against delayed draft callbacks.
    Completed calculations are always recorded against ``structure_id`` and
    ``state_id``. An SCF output may advance the workspace only while that exact
    input state is still active.

    ``atoms`` identifies the authoritative launch input and is the sole physical
    authority for its potential; potential paths are provenance/artifact metadata
    only. The request may still reference the workspace object, but the run worker
    copies it at the GUI-thread execution boundary before ASE2SPRKKR sees it.
    Lazy promotion, site initialization and backend bookkeeping therefore affect
    only the execution copy. Structural edits remain controller transitions.

    ``restart_scf`` snapshots the pending workspace execution intent. It asks
    ASE2SPRKKR to serialize ``SCFSTATUS START`` for this run without mutating the
    authoritative workspace potential.
    """

    atoms: Any
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
    """Own the next-calculation draft and an independent result tree."""

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

    def current_task(self) -> str | None:
        """Return the normalized task of the active input parameters, if known."""
        parameters = self.input_parameters
        try:
            task = str(parameters.task_name).strip().lower()
        except (AttributeError, TypeError, ValueError):
            return None
        return task or None

    def can_calculate(self) -> bool:
        if not self._workspace.can_calculate():
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

    def adopt_external_result(
        self,
        loaded: LoadedResult,
        *,
        select_result: bool = False,
    ) -> ResultAdoption:
        """Record an imported result without implicitly replacing the draft.

        ``select_result`` carries explicit presentation intent from a user-driven
        import. Background/programmatic imports leave the current result selection
        untouched.
        """
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
        if select_result:
            self.resultSelectionRequested.emit(record.id)
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
                restart_scf=self.restarted,
            )

        is_scf = _result_is_scf(loaded.result)
        output_atoms = loaded.atoms if is_scf and loaded.atoms is not None else None
        record = self._results.add_result(
            loaded.result,
            structure_id=request.structure_id,
            input_state_id=request.state_id,
            input_parameters=request.input_parameters,
            directory=request.directory,
            restart_scf=request.restart_scf,
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
            and output_atoms is not None
            and record.output_state_id is not None
            and request.structure_id == self._workspace.structure_id
            and request.state_id == self._workspace.state_id
        ):
            state = self._results.state(record.output_state_id)
            self._workspace.atoms = output_atoms
            self._workspace.potential_path = state.potential_path
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

    def _known_state_for_potential(
        self,
        version: PotentialFileVersion,
        *,
        structure_id: int,
    ) -> CalculationStateRecord | None:
        return self._results.state_for_potential_version(
            version,
            structure_id=structure_id,
        )

    @staticmethod
    def _load_potential_version(version: PotentialFileVersion) -> Any:
        current = version.current()
        if not current.available or current != version:
            raise PotentialVersionChanged(
                f"Potential file changed after it was presented: {version.path}"
            )
        try:
            atoms = load_potential_atoms(version.path)
        except OSError as exc:
            raise PotentialVersionChanged(
                f"Potential file changed while it was being read: {version.path}"
            ) from exc
        after = version.current()
        if not after.available or after != version:
            raise PotentialVersionChanged(
                f"Potential file changed while it was being read: {version.path}"
            )
        return atoms

    def _restore_state_atoms(self, state: CalculationStateRecord) -> Any:
        version = state.potential_version
        if version is not None and version.available:
            return self._load_potential_version(version)
        if state.structure_snapshot is not None:
            return state.structure_snapshot.to_atoms()
        raise ValueError("The selected result no longer has a reusable calculation input.")

    def use_result_state(
        self,
        result_id: int,
        expected_potential: PotentialFileVersion | None = None,
    ) -> None:
        """Activate a reconstructable historical state or approved current POTFIL."""
        record = self._results.result(result_id)
        state_id = record.output_state_id or record.input_state_id
        if state_id is None:
            raise ValueError("The selected result has no reusable calculation input.")
        state = self._results.state(state_id)

        target_state = state
        if expected_potential is not None:
            if state.potential_path is None:
                raise ValueError("The selected result has no reusable potential.")
            state_path = Path(state.potential_path).expanduser().absolute()
            if expected_potential.path != state_path:
                raise ValueError("The approved potential does not belong to this result.")

            current = expected_potential.current()
            if not current.available or current != expected_potential:
                raise PotentialVersionChanged(
                    f"Potential file changed after it was presented: {expected_potential.path}"
                )

            if self.state_id is not None:
                active = self._results.state(self.state_id)
                if (
                    active.structure_id == state.structure_id
                    and active.potential_version == expected_potential
                ):
                    return

            atoms = None
            if state.potential_version != expected_potential:
                known_state = self._known_state_for_potential(
                    expected_potential,
                    structure_id=state.structure_id,
                )
                if known_state is not None:
                    target_state = known_state
                else:
                    atoms = self._load_potential_version(expected_potential)
                    _, target_state_id = self._results.new_structure_state(
                        atoms,
                        potential_path=str(expected_potential.path),
                        potential_version=expected_potential,
                    )
                    target_state = self._results.state(target_state_id)
            if atoms is None:
                atoms = self._load_potential_version(expected_potential)
        else:
            atoms = self._restore_state_atoms(target_state)

        self._workspace.atoms = atoms
        self._workspace.potential_path = target_state.potential_path
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
            input_parameters=empty_spheres.parameters,
            directory=self.directory,
            output_atoms=updated if structure_changed else None,
            output_potential_path=(None if structure_changed else self.potential_path),
            output_empty_spheres=empty_spheres,
        )

        assert record.output_state_id is not None
        state = self._results.state(record.output_state_id)
        active_atoms = updated if structure_changed else source
        self._workspace.atoms = active_atoms
        self._workspace.potential_path = state.potential_path
        self._workspace.empty_spheres = state.empty_spheres
        self._workspace.state_id = state.id
        if structure_changed:
            self._workspace.restarted = True
        self._changed()
        if structure_changed:
            self.structureChanged.emit(active_atoms)

        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
