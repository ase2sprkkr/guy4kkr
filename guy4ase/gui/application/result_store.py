"""Calculation-result provenance independent of the mutable workspace draft."""
from __future__ import annotations

import stat as stat_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guy4ase.physics.composition import structure_formula

_KEEP_POTENTIAL = object()
_KEEP_POTENTIAL_SOURCE = object()


def _task_name(result: Any) -> str:
    try:
        return str(result.task_name).strip().lower()
    except (AttributeError, TypeError, ValueError):
        return type(result).__name__.lower()


@dataclass(frozen=True)
class PotentialFileVersion:
    """Cheap identity of one concrete version of a potential file.

    The file contents are deliberately not retained or hashed.  Provenance only
    needs to distinguish ordinary replacement/modification of a file while still
    remembering the path whose current version may later be reused.
    """

    path: Path
    is_file: bool
    mtime_ns: int | None
    ctime_ns: int | None
    size: int | None
    device: int | None
    inode: int | None

    @classmethod
    def capture(cls, path: str | Path) -> "PotentialFileVersion":
        resolved = Path(path).expanduser().absolute()
        try:
            info = resolved.stat()
        except OSError:
            return cls(resolved, False, None, None, None, None, None)
        return cls(
            resolved,
            stat_module.S_ISREG(info.st_mode),
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_size,
            info.st_dev,
            info.st_ino,
        )

    @property
    def available(self) -> bool:
        """Whether this captured version represented a regular file."""
        return self.is_file and self.mtime_ns is not None

    def current(self) -> "PotentialFileVersion":
        """Capture the file currently present at the same path."""
        return type(self).capture(self.path)

    def is_current(self) -> bool:
        """Whether this exact captured version is still present on disk."""
        current = self.current()
        return current.available and current == self


@dataclass(frozen=True)
class StructureGroup:
    """Identity and display metadata for one physical structure."""

    id: int
    formula: str


@dataclass(frozen=True)
class CalculationStateRecord:
    """One structure/potential state in a calculation lineage.

    The state deliberately does not retain ``Atoms``.  Structure data lives in
    the mutable workspace while completed-result provenance keeps only assigned
    identities and the cheap identity of the potential file version.  Historical
    states are therefore reusable only while their potential can be reconstructed
    from the filesystem.

    ``potential_source_result_id`` identifies the SCF result that produced the
    state's potential.  It is preserved across states that deliberately reuse the
    same potential and cleared when an operation invalidates it.
    """

    id: int
    structure_id: int
    parent_id: int | None
    lineage_id: int
    potential: PotentialFileVersion | None
    produced_by_result_id: int | None = None
    potential_source_result_id: int | None = None

    @property
    def potential_path(self) -> str | None:
        return str(self.potential.path) if self.potential is not None else None


@dataclass(frozen=True)
class ResultRecord:
    """Lightweight provenance captured for one completed calculation/operation."""

    id: int
    result: Any
    structure_id: int | None
    input_state_id: int | None
    output_state_id: int | None
    input_parameters: Any | None
    directory: str | None
    input_potential: PotentialFileVersion | None = None
    output_potential: PotentialFileVersion | None = None
    output_path: Path | None = None
    potential_path: Path | None = None
    imported: bool = False

    @property
    def task_name(self) -> str:
        return _task_name(self.result)


@dataclass
class _CalculationLineage:
    """Internal index for one alternative calculation path."""

    id: int
    structure_id: int
    result_ids: list[int] = field(default_factory=list)


class ResultStore:
    """Own exact result provenance independently of its GUI projection."""

    def __init__(self) -> None:
        self._next_structure_id = 1
        self._next_state_id = 1
        self._next_result_id = 1
        self._next_lineage_id = 1
        self._structures: dict[int, StructureGroup] = {}
        self._states: dict[int, CalculationStateRecord] = {}
        self._results: dict[int, ResultRecord] = {}
        self._lineages: dict[int, _CalculationLineage] = {}
        self._structure_lineages: dict[int, list[int]] = {}
        self._state_children: dict[int, list[int]] = {}
        self._result_ids_by_state: dict[int, list[int]] = {}
        self._unstructured_result_ids: list[int] = []
        self._imported_result_ids_by_directory: dict[str | None, list[int]] = {}

    def __len__(self) -> int:
        return len(self._results)

    def __bool__(self) -> bool:
        return bool(self._results)

    @property
    def structures(self) -> tuple[StructureGroup, ...]:
        return tuple(self._structures.values())

    @property
    def import_directories(self) -> tuple[str | None, ...]:
        """Return imported-result directories in first-import order."""
        return tuple(self._imported_result_ids_by_directory)

    @property
    def unstructured_results(self) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._unstructured_result_ids
        )

    def imported_results(self, directory: str | None) -> tuple[ResultRecord, ...]:
        """Return results explicitly imported from one source directory."""
        return tuple(
            self._results[result_id]
            for result_id in self._imported_result_ids_by_directory.get(directory, ())
        )

    def structure(self, structure_id: int) -> StructureGroup:
        return self._structures[structure_id]

    def state(self, state_id: int) -> CalculationStateRecord:
        return self._states[state_id]

    def result(self, result_id: int) -> ResultRecord:
        return self._results[result_id]

    def state_for_result(self, record: ResultRecord) -> CalculationStateRecord | None:
        state_id = record.output_state_id or record.input_state_id
        return self._states.get(state_id) if state_id is not None else None

    def potential_source_result(self, state_id: int | None) -> ResultRecord | None:
        """Return the SCF result that produced the potential used by ``state_id``."""
        if state_id is None:
            return None
        source_id = self.state(state_id).potential_source_result_id
        return self._results.get(source_id) if source_id is not None else None

    def lineage_id_for_result(self, record: ResultRecord) -> int | None:
        state = self.state_for_result(record)
        return state.lineage_id if state is not None else None

    def lineage_ids(self, structure_id: int) -> tuple[int, ...]:
        """Return native lineages which currently contain at least one result."""
        return tuple(
            lineage_id
            for lineage_id in self._structure_lineages.get(structure_id, ())
            if self._lineages[lineage_id].result_ids
        )

    def results_in_lineage(
        self,
        structure_id: int,
        lineage_id: int,
    ) -> tuple[ResultRecord, ...]:
        """Return one native lineage in result-recording order."""
        lineage = self._lineages[lineage_id]
        if lineage.structure_id != structure_id:
            raise ValueError("Lineage does not belong to the requested structure.")
        return tuple(self._results[result_id] for result_id in lineage.result_ids)

    def structure_results(self, structure_id: int) -> tuple[ResultRecord, ...]:
        """Return native results for one structure in recording order."""
        result_ids = [
            result_id
            for lineage_id in self._structure_lineages.get(structure_id, ())
            for result_id in self._lineages[lineage_id].result_ids
        ]
        result_ids.sort()
        return tuple(self._results[result_id] for result_id in result_ids)

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
        potential_version: PotentialFileVersion | None = None,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
    ) -> tuple[int, int]:
        """Create a new physical-structure group and its initial state.

        ``potential_version`` is used when the caller has already read and
        verified that exact file version.  In that case the store must not stat
        the path again and accidentally associate different provenance with the
        parsed structure.
        """
        if potential_version is not None:
            if potential_path is None:
                raise AssertionError(
                    "A captured potential version requires its potential path."
                )
            resolved_path = Path(potential_path).expanduser().absolute()
            if potential_version.path != resolved_path:
                raise AssertionError(
                    "Captured potential version does not match potential path."
                )
            resolved_potential = potential_version
        else:
            resolved_potential = self._potential_version(potential_path)

        structure_id = self._next_structure_id
        self._next_structure_id += 1
        formula = structure_formula(atoms) or type(atoms).__name__
        self._structures[structure_id] = StructureGroup(structure_id, formula)
        lineage_id = self._allocate_lineage(structure_id)
        state_id = self._new_state(
            structure_id,
            potential=resolved_potential,
            parent_id=None,
            lineage_id=lineage_id,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
        )
        return structure_id, state_id

    def new_child_state(
        self,
        parent_id: int,
        *,
        atoms: Any | None = None,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None | object = _KEEP_POTENTIAL_SOURCE,
        new_lineage: bool = False,
    ) -> int:
        """Create a state below ``parent_id`` without retaining ``atoms``."""
        del atoms  # accepted for compatibility; ResultStore does not own structures
        parent = self.state(parent_id)
        reuses_potential = potential_path is _KEEP_POTENTIAL
        resolved_potential = (
            parent.potential
            if reuses_potential
            else self._potential_version(potential_path)
        )
        resolved_source = (
            parent.potential_source_result_id
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE and reuses_potential
            else None
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE
            else potential_source_result_id
        )
        if resolved_potential is None:
            resolved_source = None

        same_lineage_child_exists = any(
            self.state(child_id).lineage_id == parent.lineage_id
            for child_id in self._state_children.get(parent_id, ())
        )
        lineage_id = (
            self._allocate_lineage(parent.structure_id)
            if new_lineage or same_lineage_child_exists
            else parent.lineage_id
        )
        return self._new_state(
            parent.structure_id,
            potential=resolved_potential,
            parent_id=parent.id,
            lineage_id=lineage_id,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=resolved_source,
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
        imported: bool = False,
    ) -> ResultRecord:
        del atoms  # provenance intentionally does not retain the mutable structure
        result_id = self._next_result_id
        self._next_result_id += 1
        task_name = _task_name(result)
        potential_source_result_id = (
            result_id
            if task_name == "scf" and output_potential_path is not None
            else None
        )

        input_potential = (
            self.state(input_state_id).potential
            if input_state_id is not None
            else None
        )
        output_state_id = None
        if output_atoms is not None:
            if structure_id is None:
                structure_id, output_state_id = self.new_structure_state(
                    output_atoms,
                    potential_path=output_potential_path,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )
            else:
                if input_state_id is None:
                    raise ValueError("A derived result requires an input state.")
                output_state_id = self.new_child_state(
                    input_state_id,
                    atoms=output_atoms,
                    potential_path=output_potential_path,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )

        output_potential = (
            self.state(output_state_id).potential
            if output_state_id is not None
            else None
        )
        record = ResultRecord(
            id=result_id,
            result=result,
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            input_parameters=input_parameters,
            directory=directory,
            input_potential=input_potential,
            output_potential=output_potential,
            output_path=output_path,
            potential_path=potential_path,
            imported=imported,
        )
        self._results[result_id] = record

        if imported:
            self._imported_result_ids_by_directory.setdefault(directory, []).append(result_id)

        state_id = output_state_id or input_state_id
        if state_id is None:
            if not imported:
                self._unstructured_result_ids.append(result_id)
        else:
            state = self.state(state_id)
            if not imported:
                self._lineages[state.lineage_id].result_ids.append(result_id)
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
                imported=True,
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
                imported=True,
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
            imported=True,
        )

    @staticmethod
    def _potential_version(path: str | Path | None | object) -> PotentialFileVersion | None:
        if path is None:
            return None
        if path is _KEEP_POTENTIAL:
            raise ValueError("_KEEP_POTENTIAL must be resolved before capture.")
        return PotentialFileVersion.capture(path)

    def _allocate_lineage(self, structure_id: int) -> int:
        lineage_id = self._next_lineage_id
        self._next_lineage_id += 1
        self._lineages[lineage_id] = _CalculationLineage(
            id=lineage_id,
            structure_id=structure_id,
        )
        self._structure_lineages.setdefault(structure_id, []).append(lineage_id)
        return lineage_id

    def _new_state(
        self,
        structure_id: int,
        *,
        potential: PotentialFileVersion | None,
        parent_id: int | None,
        lineage_id: int,
        produced_by_result_id: int | None,
        potential_source_result_id: int | None,
    ) -> int:
        state_id = self._next_state_id
        self._next_state_id += 1
        self._states[state_id] = CalculationStateRecord(
            id=state_id,
            structure_id=structure_id,
            parent_id=parent_id,
            lineage_id=lineage_id,
            potential=potential,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
        )
        if parent_id is not None:
            self._state_children.setdefault(parent_id, []).append(state_id)
        return state_id
