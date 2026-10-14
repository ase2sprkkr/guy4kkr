"""Stateful in-session calculation history and provenance-graph invariants."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from guy4ase.gui.application.file_version import FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_capture import CapturedResult, CapturedStructure
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.gui.application.workspace import EmptySpheresState

_KEEP_POTENTIAL = object()
_KEEP_EMPTY_SPHERES = object()
_KEEP_POTENTIAL_SOURCE = object()
_KEEP_STRUCTURE = object()


@dataclass(frozen=True)
class StructureRecord:
    """Identity of one user-visible physical structure."""

    id: int
    formula: str


@dataclass(frozen=True)
class CalculationStateRecord:
    """One immutable node in a structure's calculation lineage."""

    id: int
    structure_id: int
    parent_id: int | None
    branch_id: int
    potential_path: str | None
    potential_version: PotentialFileVersion | None
    structure_snapshot: StructureSnapshot | None = None
    empty_spheres: EmptySpheresState | None = None
    produced_by_result_id: int | None = None
    potential_source_result_id: int | None = None


@dataclass(frozen=True)
class ResultRecord:
    """Immutable provenance captured for one completed operation."""

    id: int
    result: Any
    task_name: str
    structure_id: int | None
    input_state_id: int | None
    output_state_id: int | None
    input_parameters: Any | None
    directory: str | None
    result_files: Mapping[str, FileVersion]
    persistent_ref: str | None = None
    restart_scf: bool = False
    output_path: Path | None = None
    output_version: FileVersion | None = None
    potential_path: Path | None = None
    imported: bool = False


@dataclass(frozen=True)
class _PreparedState:
    """A graph transition validated before mutation is committed."""

    state: CalculationStateRecord
    structure: StructureRecord | None = None
    creates_branch: bool = False


class ResultHistory:
    """Own result records, lineage and indexes without observing external state.

    All backend objects, filesystem versions and structure snapshots must be
    captured before entering this aggregate. Private prepare/commit operations
    therefore perform only deterministic in-memory validation and mutation.
    """

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
        """Return results newest first."""
        return tuple(
            self._results[result_id]
            for result_id in sorted(self._results, reverse=True)
        )

    @property
    def structures(self) -> tuple[StructureRecord, ...]:
        return tuple(self._structures.values())

    def structure(self, structure_id: int) -> StructureRecord:
        return self._structures[structure_id]

    def state(self, state_id: int) -> CalculationStateRecord:
        return self._states[state_id]

    def result(self, result_id: int) -> ResultRecord:
        return self._results[result_id]

    def result_for_persistent_ref(self, persistent_ref: str) -> ResultRecord | None:
        for record in self.results:
            if record.persistent_ref == persistent_ref:
                return record
        return None

    def state_for_result(self, record: ResultRecord) -> CalculationStateRecord | None:
        state_id = record.output_state_id or record.input_state_id
        return self._states.get(state_id) if state_id is not None else None

    def state_for_potential_version(
        self,
        version: PotentialFileVersion,
        *,
        structure_id: int | None = None,
    ) -> CalculationStateRecord | None:
        """Return the newest state known to represent this exact POTFIL version."""
        for state_id in sorted(self._states, reverse=True):
            state = self._states[state_id]
            if structure_id is not None and state.structure_id != structure_id:
                continue
            if state.potential_version == version:
                return state
        return None

    def potential_source_result(self, state_id: int | None) -> ResultRecord | None:
        if state_id is None:
            return None
        source_id = self.state(state_id).potential_source_result_id
        return self._results.get(source_id) if source_id is not None else None

    def branch_id_for_result(self, record: ResultRecord) -> int | None:
        state = self.state_for_result(record)
        return state.branch_id if state is not None else None

    def results_for_state(self, state_id: int) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._result_ids_by_state.get(state_id, ())
        )

    def latest_result_for_state(self, state_id: int | None) -> ResultRecord | None:
        if state_id is None:
            return None
        result_ids = self._result_ids_by_state.get(state_id, ())
        if not result_ids:
            return None
        return self._results[result_ids[-1]]

    @staticmethod
    def _validate_captured_structure(captured: CapturedStructure) -> None:
        version = captured.potential_version
        path = captured.potential_path
        snapshot = captured.structure_snapshot
        if version is None:
            if path is not None:
                raise AssertionError("A potential path requires a captured version.")
            if snapshot is None:
                raise ValueError("A state without a potential requires a structure snapshot.")
            return
        if path is None:
            raise AssertionError("A captured potential version requires its potential path.")
        if version.available:
            if snapshot is not None:
                raise AssertionError("A usable potential must be the sole structure authority.")
        elif snapshot is None:
            raise ValueError("An unavailable potential requires a structure snapshot.")

    def _prepare_structure_state(
        self,
        captured: CapturedStructure,
        *,
        empty_spheres: EmptySpheresState | None = None,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
    ) -> _PreparedState:
        self._validate_captured_structure(captured)
        source_result_id = (
            potential_source_result_id
            if captured.potential_version is not None
            and captured.potential_version.available
            else None
        )
        structure = StructureRecord(self._next_structure_id, captured.formula)
        state = CalculationStateRecord(
            id=self._next_state_id,
            structure_id=structure.id,
            parent_id=None,
            branch_id=self._next_branch_id,
            potential_path=captured.potential_path,
            potential_version=captured.potential_version,
            structure_snapshot=captured.structure_snapshot,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=source_result_id,
        )
        return _PreparedState(state=state, structure=structure, creates_branch=True)

    def _prepare_child_state(
        self,
        parent_id: int,
        *,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        potential_version: PotentialFileVersion | None = None,
        structure_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None | object = _KEEP_POTENTIAL_SOURCE,
        new_branch: bool = False,
    ) -> _PreparedState:
        parent = self.state(parent_id)
        reuses_potential = potential_path is _KEEP_POTENTIAL
        if reuses_potential:
            if potential_version is not None:
                raise AssertionError(
                    "An explicit potential version requires an explicit potential path."
                )
            resolved_path = parent.potential_path
            resolved_version = parent.potential_version
        else:
            resolved_path = potential_path
            resolved_version = potential_version
            if resolved_path is not None and resolved_version is None:
                raise AssertionError(
                    "An explicit potential path must be captured before history mutation."
                )
            if resolved_version is not None:
                if resolved_path is None:
                    raise AssertionError(
                        "A captured potential version requires its potential path."
                    )
                if Path(resolved_path).is_absolute() and Path(resolved_path) != resolved_version.path:
                    raise AssertionError(
                        "Captured potential version does not match potential path."
                    )

        resolved_source = (
            parent.potential_source_result_id
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE and reuses_potential
            else None
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE
            else potential_source_result_id
        )
        if resolved_version is None or not resolved_version.available:
            resolved_source = None

        if resolved_version is None or not resolved_version.available:
            resolved_snapshot = (
                parent.structure_snapshot
                if structure_snapshot is _KEEP_STRUCTURE
                else structure_snapshot
            )
            if resolved_snapshot is None:
                raise ValueError(
                    "A state without a usable potential requires a structure snapshot."
                )
        else:
            resolved_snapshot = None

        resolved_empty_spheres = (
            parent.empty_spheres
            if empty_spheres is _KEEP_EMPTY_SPHERES
            else empty_spheres
        )
        same_branch_child_exists = any(
            self.state(child_id).branch_id == parent.branch_id
            for child_id in self._state_children.get(parent_id, ())
        )
        creates_branch = new_branch or same_branch_child_exists
        branch_id = self._next_branch_id if creates_branch else parent.branch_id
        state = CalculationStateRecord(
            id=self._next_state_id,
            structure_id=parent.structure_id,
            parent_id=parent.id,
            branch_id=branch_id,
            potential_path=resolved_path,
            potential_version=resolved_version,
            structure_snapshot=resolved_snapshot,
            empty_spheres=resolved_empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=resolved_source,
        )
        return _PreparedState(state=state, creates_branch=creates_branch)

    def _validate_prepared_state(self, prepared: _PreparedState) -> None:
        state = prepared.state
        if state.id != self._next_state_id:
            raise AssertionError("Prepared state no longer matches the history counter.")
        if prepared.structure is not None:
            if prepared.structure.id != self._next_structure_id:
                raise AssertionError(
                    "Prepared structure no longer matches the history counter."
                )
            if state.structure_id != prepared.structure.id:
                raise AssertionError("Prepared state belongs to the wrong structure.")
        elif state.structure_id not in self._structures:
            raise AssertionError("Prepared state belongs to an unknown structure.")
        if prepared.creates_branch and state.branch_id != self._next_branch_id:
            raise AssertionError("Prepared state no longer matches the branch counter.")

    def _commit_prepared_state(self, prepared: _PreparedState) -> None:
        self._validate_prepared_state(prepared)
        state = prepared.state
        if prepared.structure is not None:
            self._structures[prepared.structure.id] = prepared.structure
            self._next_structure_id += 1
        if prepared.creates_branch:
            self._next_branch_id += 1
        self._states[state.id] = state
        self._next_state_id += 1
        if state.parent_id is not None:
            self._state_children.setdefault(state.parent_id, []).append(state.id)

    def add_structure_state(
        self,
        captured: CapturedStructure,
        *,
        empty_spheres: EmptySpheresState | None = None,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
    ) -> tuple[int, int]:
        prepared = self._prepare_structure_state(
            captured,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
        )
        self._commit_prepared_state(prepared)
        assert prepared.structure is not None
        return prepared.structure.id, prepared.state.id

    def add_child_state(
        self,
        parent_id: int,
        *,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        potential_version: PotentialFileVersion | None = None,
        structure_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None | object = _KEEP_POTENTIAL_SOURCE,
        new_branch: bool = False,
    ) -> int:
        prepared = self._prepare_child_state(
            parent_id,
            potential_path=potential_path,
            potential_version=potential_version,
            structure_snapshot=structure_snapshot,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
            new_branch=new_branch,
        )
        self._commit_prepared_state(prepared)
        return prepared.state.id

    def _commit_result(
        self,
        record: ResultRecord,
        *,
        prepared_state: _PreparedState | None = None,
    ) -> None:
        if record.id != self._next_result_id:
            raise AssertionError("Prepared result no longer matches the history counter.")
        if prepared_state is not None:
            self._validate_prepared_state(prepared_state)
            if prepared_state.state.id not in (
                record.input_state_id,
                record.output_state_id,
            ):
                raise AssertionError(
                    "Prepared result does not reference its prepared state."
                )

        if prepared_state is not None:
            self._commit_prepared_state(prepared_state)
        self._results[record.id] = record
        self._next_result_id += 1

        state_id = record.output_state_id or record.input_state_id
        if state_id is not None:
            self._result_ids_by_state.setdefault(state_id, []).append(record.id)

    def add_result(
        self,
        captured: CapturedResult,
        *,
        structure_id: int | None,
        input_state_id: int | None,
        directory: str | None,
        persistent_ref: str | None = None,
        restart_scf: bool = False,
        output_structure: CapturedStructure | None = None,
        output_structure_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE,
        output_potential_path: str | None | object = _KEEP_POTENTIAL,
        output_potential_version: PotentialFileVersion | None = None,
        output_empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        imported: bool = False,
    ) -> ResultRecord:
        if (structure_id is None) != (input_state_id is None):
            raise ValueError(
                "Result provenance requires structure_id and input_state_id together."
            )

        input_state = None
        if input_state_id is not None:
            input_state = self.state(input_state_id)
            if input_state.structure_id != structure_id:
                raise AssertionError(
                    "Result provenance mismatch: input state "
                    f"{input_state_id} belongs to structure "
                    f"{input_state.structure_id}, not {structure_id}."
                )

        result_id = self._next_result_id
        potential_source_result_id = (
            result_id
            if captured.task_name == "scf"
            and output_potential_path is not _KEEP_POTENTIAL
            and output_potential_path is not None
            else None
        )

        prepared_state = None
        output_state_id = None
        produces_state = (
            output_structure is not None
            or output_structure_snapshot is not _KEEP_STRUCTURE
            or output_empty_spheres is not _KEEP_EMPTY_SPHERES
        )
        if produces_state:
            if structure_id is None:
                if output_structure is None:
                    raise ValueError("A new structure state requires captured structure.")
                root_empty_spheres = (
                    None
                    if output_empty_spheres is _KEEP_EMPTY_SPHERES
                    else output_empty_spheres
                )
                prepared_state = self._prepare_structure_state(
                    output_structure,
                    empty_spheres=root_empty_spheres,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )
                assert prepared_state.structure is not None
                structure_id = prepared_state.structure.id
            else:
                if input_state is None:
                    raise ValueError("A derived result requires an input state.")
                prepared_state = self._prepare_child_state(
                    input_state_id,
                    potential_path=output_potential_path,
                    potential_version=output_potential_version,
                    structure_snapshot=output_structure_snapshot,
                    empty_spheres=output_empty_spheres,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )
            output_state_id = prepared_state.state.id

        record = ResultRecord(
            id=result_id,
            result=captured.result,
            task_name=captured.task_name,
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            input_parameters=captured.input_parameters,
            directory=directory,
            result_files=captured.result_files,
            persistent_ref=persistent_ref,
            restart_scf=restart_scf,
            output_path=captured.output_path,
            output_version=captured.output_version,
            potential_path=captured.potential_path,
            imported=imported,
        )
        self._commit_result(record, prepared_state=prepared_state)
        return record

    def add_external_result(
        self,
        captured: CapturedResult,
        *,
        structure: CapturedStructure | None,
        directory: str | None,
        produces_state: bool,
        persistent_ref: str | None = None,
    ) -> ResultRecord:
        if structure is None:
            return self.add_result(
                captured,
                structure_id=None,
                input_state_id=None,
                directory=directory,
                persistent_ref=persistent_ref,
                imported=True,
            )

        if produces_state:
            return self.add_result(
                captured,
                structure_id=None,
                input_state_id=None,
                directory=directory,
                persistent_ref=persistent_ref,
                output_structure=structure,
                output_potential_path=structure.potential_path,
                output_potential_version=structure.potential_version,
                imported=True,
            )

        prepared_state = self._prepare_structure_state(structure)
        assert prepared_state.structure is not None
        record = ResultRecord(
            id=self._next_result_id,
            result=captured.result,
            task_name=captured.task_name,
            structure_id=prepared_state.structure.id,
            input_state_id=prepared_state.state.id,
            output_state_id=None,
            input_parameters=captured.input_parameters,
            directory=directory,
            result_files=captured.result_files,
            persistent_ref=persistent_ref,
            output_path=captured.output_path,
            output_version=captured.output_version,
            potential_path=captured.potential_path,
            imported=True,
        )
        self._commit_result(record, prepared_state=prepared_state)
        return record
