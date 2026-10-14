"""Resolve reusable historical calculation state without mutating a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_history import CalculationStateRecord, ResultHistory
from guy4ase.gui.application.result_loading import (
    load_potential_version,
    require_potential_version_current,
)


@dataclass(frozen=True)
class ExistingHistoricalState:
    """A historical input already represented by a recorded calculation state."""

    atoms: Any
    state: CalculationStateRecord


@dataclass(frozen=True)
class NewHistoricalPotential:
    """A user-approved POTFIL version not yet represented in the result lineage."""

    atoms: Any
    parent_state: CalculationStateRecord
    potential_version: PotentialFileVersion


@dataclass(frozen=True)
class HistoricalStateAlreadyActive:
    """The approved historical calculation input is already the active state."""


HistoricalStateResolution = Union[
    ExistingHistoricalState,
    NewHistoricalPotential,
    HistoricalStateAlreadyActive,
]


def _state_for_result(
    history: ResultHistory,
    result_id: int,
) -> CalculationStateRecord:
    record = history.result(result_id)
    state_id = record.output_state_id or record.input_state_id
    if state_id is None:
        raise ValueError("The selected result has no reusable calculation input.")
    return history.state(state_id)


def _restore_state_atoms(state: CalculationStateRecord) -> Any:
    return state.structure_provenance.materialize()


def resolve_historical_state(
    history: ResultHistory,
    result_id: int,
    *,
    active_state_id: int | None = None,
    expected_potential: PotentialFileVersion | None = None,
) -> HistoricalStateResolution:
    """Resolve the physical input for a result without mutating ``history``."""
    state = _state_for_result(history, result_id)
    if expected_potential is None:
        return ExistingHistoricalState(
            atoms=_restore_state_atoms(state),
            state=state,
        )

    if state.potential_path is None:
        raise ValueError("The selected result has no reusable potential.")
    state_path = Path(state.potential_path).expanduser().resolve()
    if expected_potential.path != state_path:
        raise ValueError("The approved potential does not belong to this result.")

    if active_state_id is not None:
        active = history.state(active_state_id)
        if (
            active.structure_id == state.structure_id
            and active.potential_version == expected_potential
        ):
            require_potential_version_current(expected_potential)
            return HistoricalStateAlreadyActive()

    if state.potential_version == expected_potential:
        target_state = state
    else:
        target_state = history.state_for_potential_version(
            expected_potential,
            structure_id=state.structure_id,
        )

    atoms = load_potential_version(expected_potential)
    if target_state is not None:
        return ExistingHistoricalState(atoms=atoms, state=target_state)
    return NewHistoricalPotential(
        atoms=atoms,
        parent_state=state,
        potential_version=expected_potential,
    )
