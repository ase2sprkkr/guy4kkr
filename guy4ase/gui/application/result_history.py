"""Stateful in-session calculation history and provenance-graph invariants."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from guy4ase.gui.application.file_version import FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.gui.application.workspace import EmptySpheresState

_KEEP_EMPTY_SPHERES = object()


@dataclass(frozen=True)
class CapturedStructure:
    """Detached physical structure provenance ready for history mutation."""

    formula: str
    potential_path: Path | None
    potential_version: PotentialFileVersion | None
    structure_snapshot: StructureSnapshot | None


@dataclass(frozen=True)
class CapturedResult:
    """Detached result provenance plus an opaque read-only result payload."""

    result: Any
    task_name: str
    input_parameters: Any | None
    result_files: Mapping[str, FileVersion]
    output_path: Path | None
    output_version: FileVersion | None
    potential_path: Path | None


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
    potential_path: Path | None
    potential_version: PotentialFileVersion | None
    structure_snapshot: StructureSnapshot | None = None
    empty_spheres: EmptySpheresState | None = None
    produced_by_result_id: int | None = None
    potential_source_result_id: int | None = None


@dataclass(frozen=True)
class ResultRecord:
    """Immutable provenance captured for one completed operation.

    ``result`` is an opaque runtime payload retained for presentation. History
    never derives provenance invariants from mutable state inside that payload.
    """

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

    Backend objects, filesystem versions and structure snapshots are captured
    before entering this aggregate. Prepare/commit operations therefore perform
    only deterministic in-memory validation and mutation.
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
        """Return results attached to ``state_id`` as their effective state."""
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
        if path != version.path:
            raise AssertionError("Captured potential version does not match potential path.")
        if version.available:
            if snapshot is not None:
                raise AssertionError("A usable potential must be the sole structure authority.")
        elif snapshot is None:
            raise ValueError("An unavailable potential requires a structure snapshot.")

    def _validate_result_reference(
        self,
        result_id: int | None,
        *,
        pending_result_id: int | None = None,
    ) -> None:
        if result_id is None:
            return
        if result_id == pending_result_id:
            return
        if result_id not in self._results:
            raise AssertionError(f"State refers to unknown result {result_id}.")

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
        structure: CapturedStructure | None = None,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
        source_result_explicit: bool = False,
        new_branch: bool = False,
    ) -> _PreparedState:
        parent = self.state(parent_id)
        if structure is None:
            resolved_path = parent.potential_path
            resolved_version = parent.potential_version
            resolved_snapshot = parent.structure_snapshot
            resolved_source = parent.potential_source_result_id
        else:
            self._validate_captured_structure(structure)
            resolved_path = structure.potential_path
            resolved_version = structure.potential_version
            resolved_snapshot = structure.structure_snapshot
            if resolved_version is None or not resolved_version.available:
                resolved_source = None
            elif source_result_explicit:
                resolved_source = potential_source_result_id
            elif resolved_version == parent.potential_version:
                resolved_source = parent.potential_source_result_id
            else:
                resolved_source = None

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

    def _validate_prepared_state(
        self,
        prepared: _PreparedState,
        *,
        pending_result_id: int | None = None,
    ) -> None:
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
        self._validate_result_reference(
            state.produced_by_result_id,
            pending_result_id=pending_result_id,
        )
        self._validate_result_reference(
            state.potential_source_result_id,
            pending_result_id=pending_result_id,
        )

    def _commit_prepared_state(
        self,
        prepared: _PreparedState,
        *,
        pending_result_id: int | None = None,
    ) -> None:
        self._validate_prepared_state(
            prepared,
            pending_result_id=pending_result_id,
        )
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
    ) -> tuple[int, int]:
        prepared = self._prepare_structure_state(
            captured,
            empty_spheres=empty_spheres,
        )
        self._commit_prepared_state(prepared)
        assert prepared.structure is not None
        return prepared.structure.id, prepared.state.id

    def add_child_state(
        self,
        parent_id: int,
        *,
        structure: CapturedStructure | None = None,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        new_branch: bool = False,
    ) -> int:
        prepared = self._prepare_child_state(
            parent_id,
            structure=structure,
            empty_spheres=empty_spheres,
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
            self._validate_prepared_state(
                prepared_state,
                pending_result_id=record.id,
            )
            if prepared_state.state.id not in (
                record.input_state_id,
                record.output_state_id,
            ):
                raise AssertionError(
                    "Prepared result does not reference its prepared state."
                )

        if prepared_state is not None:
            self._commit_prepared_state(
                prepared_state,
                pending_result_id=record.id,
            )
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
        produces_state = (
            output_structure is not None
            or output_empty_spheres is not _KEEP_EMPTY_SPHERES
        )
        source_result_id = (
            result_id
            if captured.task_name == "scf"
            and output_structure is not None
            and output_structure.potential_version is not None
            and output_structure.potential_version.available
            else None
        )

        prepared_state = None
        output_state_id = None
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
                    potential_source_result_id=source_result_id,
                )
                assert prepared_state.structure is not None
                structure_id = prepared_state.structure.id
            else:
                if input_state is None:
                    raise ValueError("A derived result requires an input state.")
                prepared_state = self._prepare_child_state(
                    input_state_id,
                    structure=output_structure,
                    empty_spheres=output_empty_spheres,
                    produced_by_result_id=result_id,
                    potential_source_result_id=source_result_id,
                    source_result_explicit=(source_result_id is not None),
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
