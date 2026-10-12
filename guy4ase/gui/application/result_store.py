"""Calculation-result provenance independent of the mutable workspace draft."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from guy4ase.physics.composition import structure_formula

_KEEP_POTENTIAL = object()


@dataclass(frozen=True)
class StructureRecord:
    """Identity of one user-visible physical structure."""

    id: int
    formula: str


@dataclass(frozen=True)
class CalculationStateRecord:
    """One concrete input state used by SPR-KKR calculations.

    State identity is assigned, never inferred from the contents. SCF and
    structure-preserving transformations such as Empty Spheres create child
    states of the same :class:`StructureRecord`.
    """

    id: int
    structure_id: int
    parent_id: int | None
    atoms: Any
    potential_path: str | None
    produced_by_result_id: int | None = None


@dataclass(frozen=True)
class ResultRecord:
    """Immutable provenance captured for one completed calculation/operation."""

    id: int
    result: Any
    structure_id: int | None
    input_state_id: int | None
    output_state_id: int | None
    atoms: Any | None
    input_parameters: Any | None
    directory: str | None
    output_path: Path | None = None
    potential_path: Path | None = None

    @property
    def task_name(self) -> str:
        try:
            return str(self.result.task_name).strip().lower()
        except (AttributeError, TypeError, ValueError):
            return type(self.result).__name__.lower()


class ResultStore:
    """Own completed results and the lineage of states they used/produced."""

    def __init__(self) -> None:
        self._next_structure_id = 1
        self._next_state_id = 1
        self._next_result_id = 1
        self._structures: dict[int, StructureRecord] = {}
        self._states: dict[int, CalculationStateRecord] = {}
        self._results: list[ResultRecord] = []

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
        return tuple(reversed(self._results))

    @property
    def structures(self) -> tuple[StructureRecord, ...]:
        return tuple(self._structures.values())

    def structure(self, structure_id: int) -> StructureRecord:
        return self._structures[structure_id]

    def state(self, state_id: int) -> CalculationStateRecord:
        return self._states[state_id]

    def result(self, result_id: int) -> ResultRecord:
        for record in self._results:
            if record.id == result_id:
                return record
        raise KeyError(result_id)

    def new_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
    ) -> tuple[int, int]:
        """Create a new user-visible structure and its initial calculation state."""
        structure_id = self._next_structure_id
        self._next_structure_id += 1
        formula = structure_formula(atoms) or type(atoms).__name__
        self._structures[structure_id] = StructureRecord(structure_id, formula)
        state_id = self._new_state(
            structure_id,
            atoms,
            potential_path=potential_path,
            parent_id=None,
            produced_by_result_id=None,
        )
        return structure_id, state_id

    def new_child_state(
        self,
        parent_id: int,
        *,
        atoms: Any | None = None,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        produced_by_result_id: int | None = None,
    ) -> int:
        """Assign a new identity derived from an existing calculation state.

        Omitting ``potential_path`` inherits the parent's potential. Passing
        ``None`` explicitly clears it. This distinction is required because an
        explicit new SCF sequence reuses its starting potential whereas a
        structure-changing operation such as Empty Spheres invalidates it.
        """
        parent = self.state(parent_id)
        resolved_potential = (
            parent.potential_path
            if potential_path is _KEEP_POTENTIAL
            else potential_path
        )
        return self._new_state(
            parent.structure_id,
            parent.atoms if atoms is None else atoms,
            potential_path=resolved_potential,
            parent_id=parent.id,
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
        output_path: Path | None = None,
        potential_path: Path | None = None,
        output_atoms: Any | None = None,
        output_potential_path: str | None = None,
    ) -> ResultRecord:
        result_id = self._next_result_id
        self._next_result_id += 1

        output_state_id = None
        if output_atoms is not None:
            if structure_id is None:
                structure_id, output_state_id = self.new_structure_state(
                    output_atoms,
                    potential_path=output_potential_path,
                )
                root = self._states[output_state_id]
                self._states[output_state_id] = CalculationStateRecord(
                    id=root.id,
                    structure_id=root.structure_id,
                    parent_id=None,
                    atoms=root.atoms,
                    potential_path=root.potential_path,
                    produced_by_result_id=result_id,
                )
            else:
                if input_state_id is None:
                    raise ValueError("A derived result requires an input state.")
                output_state_id = self.new_child_state(
                    input_state_id,
                    atoms=output_atoms,
                    potential_path=output_potential_path,
                    produced_by_result_id=result_id,
                )

        record = ResultRecord(
            id=result_id,
            result=result,
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            atoms=atoms,
            input_parameters=input_parameters,
            directory=directory,
            output_path=output_path,
            potential_path=potential_path,
        )
        self._results.append(record)
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
        """Return branch numbers only where a state actually forks."""
        state_id = record.output_state_id or record.input_state_id
        if state_id is None:
            return ()
        children = self._children_by_parent(record.structure_id)
        path: list[int] = []
        current = state_id
        while current in self._states:
            state = self._states[current]
            parent_id = state.parent_id
            if parent_id is None:
                break
            siblings = children.get(parent_id, ())
            if len(siblings) > 1:
                path.append(siblings.index(current) + 1)
            current = parent_id
        path.reverse()
        return tuple(path)

    def _children_by_parent(
        self, structure_id: int | None
    ) -> dict[int, tuple[int, ...]]:
        children: dict[int, list[int]] = {}
        for state in self._states.values():
            if state.structure_id != structure_id or state.parent_id is None:
                continue
            children.setdefault(state.parent_id, []).append(state.id)
        return {parent: tuple(sorted(ids)) for parent, ids in children.items()}

    def _new_state(
        self,
        structure_id: int,
        atoms: Any,
        *,
        potential_path: str | None,
        parent_id: int | None,
        produced_by_result_id: int | None,
    ) -> int:
        state_id = self._next_state_id
        self._next_state_id += 1
        self._states[state_id] = CalculationStateRecord(
            id=state_id,
            structure_id=structure_id,
            parent_id=parent_id,
            atoms=atoms,
            potential_path=potential_path,
            produced_by_result_id=produced_by_result_id,
        )
        return state_id
