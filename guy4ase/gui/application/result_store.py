"""Calculation-result provenance independent of the mutable workspace draft."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from guy4ase.gui.application.result_artifacts import (
    ResultArtifactVersion,
    capture_result_artifacts,
)
from guy4ase.gui.application.workspace import EmptySpheresState
from guy4ase.physics.composition import structure_formula

_KEEP_POTENTIAL = object()
_KEEP_EMPTY_SPHERES = object()


def _task_name(result: Any) -> str:
    """Capture a stable normalized task identity from a result."""
    try:
        return str(result.task_name).strip().lower()
    except (AttributeError, TypeError, ValueError):
        return type(result).__name__.lower()


def _snapshot_input_parameters(parameters: Any | None) -> Any | None:
    """Detach small mutable input provenance from its live source object."""
    if parameters is None:
        return None

    copier = getattr(parameters, "copy", None)
    if callable(copier):
        try:
            return copier(copy_values=True)
        except TypeError:
            # Generic mappings/copyables do not support ASE2SPRKKR's
            # ``copy_values`` contract; use a real deep snapshot below.
            pass

    if isinstance(parameters, Mapping):
        return deepcopy(dict(parameters))
    return deepcopy(parameters)


@dataclass(frozen=True)
class StructureRecord:
    """Identity of one user-visible physical structure."""

    id: int
    formula: str


@dataclass(frozen=True)
class CalculationStateRecord:
    """One concrete restorable state in a calculation lineage.

    Identity is assigned, never inferred from contents. ``branch_id`` is stable
    provenance: sequential state-producing operations normally keep it, while
    an explicit restart or a sibling continuation starts another branch.

    ``empty_spheres`` records metadata of the explicit empty-sphere search that
    produced this state. The atoms remain authoritative for the actual structure.
    """

    id: int
    structure_id: int
    parent_id: int | None
    branch_id: int
    atoms: Any
    potential_path: str | None
    empty_spheres: EmptySpheresState | None = None
    produced_by_result_id: int | None = None


@dataclass(frozen=True)
class ResultRecord:
    """Immutable provenance captured for one completed calculation/operation."""

    id: int
    result: Any
    task_name: str
    structure_id: int | None
    input_state_id: int | None
    output_state_id: int | None
    atoms: Any | None
    input_parameters: Any | None
    directory: str | None
    artifacts: Mapping[str, ResultArtifactVersion]
    restart_scf: bool = False
    output_path: Path | None = None
    potential_path: Path | None = None


class ResultStore:
    """Own completed results as a structure -> branch -> state/result tree."""

    def __init__(self) -> None:
        self._next_structure_id = 1
        self._next_state_id = 1
        self._next_result_id = 1
        self._next_branch_id = 1
        self._structures: dict[int, StructureRecord] = {}
        self._states: dict[int, CalculationStateRecord] = {}
        self._results: dict[int, ResultRecord] = {}
        self._state_children: dict[int, list[int]] = {}
        self._result_ids_by_state: dict[int, list[int]] = {}
        self._unstructured_result_ids: list[int] = []
        self._structure_branches: dict[int, list[int]] = {}

    def __len__(self) -> int:
        return len(self._results)

    def __bool__(self) -> bool:
        return bool(self._results)

    def __iter__(self) -> Iterator[ResultRecord]:
        return iter(self.results)

    def __getitem__(self, index):
        return self.results[index]

    @property
    def results(self) -> tuple[ResultRecord, ...]:
        """Return a newest-first compatibility view over the tree."""
        return tuple(
            self._results[result_id]
            for result_id in sorted(self._results, reverse=True)
        )

    @property
    def structures(self) -> tuple[StructureRecord, ...]:
        return tuple(self._structures.values())

    @property
    def unstructured_results(self) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._unstructured_result_ids
        )

    def structure(self, structure_id: int) -> StructureRecord:
        return self._structures[structure_id]

    def state(self, state_id: int) -> CalculationStateRecord:
        return self._states[state_id]

    def result(self, result_id: int) -> ResultRecord:
        return self._results[result_id]

    def state_for_result(self, record: ResultRecord) -> CalculationStateRecord | None:
        state_id = record.output_state_id or record.input_state_id
        return self._states.get(state_id) if state_id is not None else None

    def branch_id_for_result(self, record: ResultRecord) -> int | None:
        state = self.state_for_result(record)
        return state.branch_id if state is not None else None

    def branch_ids(self, structure_id: int) -> tuple[int, ...]:
        """Return branches which currently contain at least one result."""
        used = {
            branch_id
            for record in self._results.values()
            if record.structure_id == structure_id
            for branch_id in (self.branch_id_for_result(record),)
            if branch_id is not None
        }
        return tuple(
            branch_id
            for branch_id in self._structure_branches.get(structure_id, ())
            if branch_id in used
        )

    def branch_number(self, structure_id: int, branch_id: int) -> int:
        return self._structure_branches[structure_id].index(branch_id) + 1

    def results_in_branch(
        self, structure_id: int, branch_id: int
    ) -> tuple[ResultRecord, ...]:
        """Return one branch in calculation order."""
        return tuple(
            sorted(
                (
                    record
                    for record in self._results.values()
                    if record.structure_id == structure_id
                    and self.branch_id_for_result(record) == branch_id
                ),
                key=lambda record: record.id,
            )
        )

    def results_for_state(self, state_id: int) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._result_ids_by_state.get(state_id, ())
        )

    def latest_result_for_state(self, state_id: int | None) -> ResultRecord | None:
        """Return the latest result attached to the active state, if any."""
        if state_id is None:
            return None
        result_ids = self._result_ids_by_state.get(state_id, ())
        if not result_ids:
            return None
        return self._results[result_ids[-1]]

    def new_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
        empty_spheres: EmptySpheresState | None = None,
    ) -> tuple[int, int]:
        """Create a new user-visible structure and its initial branch/state."""
        structure_id = self._next_structure_id
        self._next_structure_id += 1
        formula = structure_formula(atoms) or type(atoms).__name__
        self._structures[structure_id] = StructureRecord(structure_id, formula)
        branch_id = self._allocate_branch(structure_id)
        state_id = self._new_state(
            structure_id,
            atoms,
            potential_path=potential_path,
            empty_spheres=empty_spheres,
            parent_id=None,
            branch_id=branch_id,
            produced_by_result_id=None,
        )
        return structure_id, state_id

    def new_child_state(
        self,
        parent_id: int,
        *,
        atoms: Any | None = None,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        new_branch: bool = False,
    ) -> int:
        """Create a state below ``parent_id`` and assign its branch.

        Sequential state changes keep the parent's branch. A second sibling
        continuation is an alternative and therefore starts another branch.
        Potential and empty-sphere provenance are inherited unless explicitly
        replaced. ``new_branch=True`` is used by an explicit continuation.
        """
        parent = self.state(parent_id)
        resolved_potential = (
            parent.potential_path
            if potential_path is _KEEP_POTENTIAL
            else potential_path
        )
        resolved_empty_spheres = (
            parent.empty_spheres
            if empty_spheres is _KEEP_EMPTY_SPHERES
            else empty_spheres
        )
        same_branch_child_exists = any(
            self.state(child_id).branch_id == parent.branch_id
            for child_id in self._state_children.get(parent_id, ())
        )
        branch_id = (
            self._allocate_branch(parent.structure_id)
            if new_branch or same_branch_child_exists
            else parent.branch_id
        )
        return self._new_state(
            parent.structure_id,
            parent.atoms if atoms is None else atoms,
            potential_path=resolved_potential,
            empty_spheres=resolved_empty_spheres,
            parent_id=parent.id,
            branch_id=branch_id,
            produced_by_result_id=produced_by_result_id,
        )

    def add_result(
        self,
        result: Any,
        *,
        structure_id: int | None,
        input_state_id: int | None,
        atoms: Any | None,
        input_parameters: Any | None,
        directory: str | None,
        restart_scf: bool = False,
        output_path: Path | None = None,
        potential_path: Path | None = None,
        output_atoms: Any | None = None,
        output_potential_path: str | None = None,
        output_empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
    ) -> ResultRecord:
        if input_state_id is not None:
            input_state = self.state(input_state_id)
            if input_state.structure_id != structure_id:
                raise AssertionError(
                    "Result provenance mismatch: input state "
                    f"{input_state_id} belongs to structure "
                    f"{input_state.structure_id}, not {structure_id}."
                )

        result_id = self._next_result_id
        self._next_result_id += 1

        output_state_id = None
        produces_state = (
            output_atoms is not None
            or output_empty_spheres is not _KEEP_EMPTY_SPHERES
        )
        if produces_state:
            if structure_id is None:
                root_empty_spheres = (
                    None
                    if output_empty_spheres is _KEEP_EMPTY_SPHERES
                    else output_empty_spheres
                )
                if output_atoms is None:
                    raise ValueError("A new structure state requires atoms.")
                structure_id, output_state_id = self.new_structure_state(
                    output_atoms,
                    potential_path=output_potential_path,
                    empty_spheres=root_empty_spheres,
                )
                root = self._states[output_state_id]
                self._states[output_state_id] = CalculationStateRecord(
                    id=root.id,
                    structure_id=root.structure_id,
                    parent_id=None,
                    branch_id=root.branch_id,
                    atoms=root.atoms,
                    potential_path=root.potential_path,
                    empty_spheres=root.empty_spheres,
                    produced_by_result_id=result_id,
                )
            else:
                if input_state_id is None:
                    raise ValueError("A derived result requires an input state.")
                output_state_id = self.new_child_state(
                    input_state_id,
                    atoms=output_atoms,
                    potential_path=output_potential_path,
                    empty_spheres=output_empty_spheres,
                    produced_by_result_id=result_id,
                )

        record = ResultRecord(
            id=result_id,
            result=result,
            task_name=_task_name(result),
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            atoms=atoms,
            input_parameters=_snapshot_input_parameters(input_parameters),
            directory=directory,
            restart_scf=restart_scf,
            output_path=output_path,
            potential_path=potential_path,
            artifacts=capture_result_artifacts(result),
        )
        self._results[result_id] = record
        state_id = output_state_id or input_state_id
        if state_id is None:
            self._unstructured_result_ids.append(result_id)
        else:
            self._result_ids_by_state.setdefault(state_id, []).append(result_id)
        return record

    def add_external_result(
        self,
        result: Any,
        *,
        atoms: Any | None,
        input_parameters: Any | None,
        directory: str | None,
        output_path: Path | None,
        potential_path: Path | None,
        produces_state: bool,
    ) -> ResultRecord:
        if atoms is None:
            return self.add_result(
                result,
                structure_id=None,
                input_state_id=None,
                atoms=None,
                input_parameters=input_parameters,
                directory=directory,
                output_path=output_path,
                potential_path=potential_path,
            )

        if produces_state:
            return self.add_result(
                result,
                structure_id=None,
                input_state_id=None,
                atoms=atoms,
                input_parameters=input_parameters,
                directory=directory,
                output_path=output_path,
                potential_path=potential_path,
                output_atoms=atoms,
                output_potential_path=(str(potential_path) if potential_path else None),
            )

        structure_id, state_id = self.new_structure_state(
            atoms,
            potential_path=(str(potential_path) if potential_path else None),
        )
        return self.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            atoms=atoms,
            input_parameters=input_parameters,
            directory=directory,
            output_path=output_path,
            potential_path=potential_path,
        )

    def branch_path(self, record: ResultRecord) -> tuple[int, ...]:
        """Compatibility presentation of the stable branch identity."""
        if record.structure_id is None:
            return ()
        branch_id = self.branch_id_for_result(record)
        branches = self.branch_ids(record.structure_id)
        if branch_id is None or len(branches) <= 1:
            return ()
        return (self.branch_number(record.structure_id, branch_id),)

    def _allocate_branch(self, structure_id: int) -> int:
        branch_id = self._next_branch_id
        self._next_branch_id += 1
        self._structure_branches.setdefault(structure_id, []).append(branch_id)
        return branch_id

    def _new_state(
        self,
        structure_id: int,
        atoms: Any,
        *,
        potential_path: str | None,
        empty_spheres: EmptySpheresState | None,
        parent_id: int | None,
        branch_id: int,
        produced_by_result_id: int | None,
    ) -> int:
        state_id = self._next_state_id
        self._next_state_id += 1
        self._states[state_id] = CalculationStateRecord(
            id=state_id,
            structure_id=structure_id,
            parent_id=parent_id,
            branch_id=branch_id,
            atoms=atoms,
            potential_path=potential_path,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
        )
        if parent_id is not None:
            self._state_children.setdefault(parent_id, []).append(state_id)
        return state_id
