"""Restore and recompute policy for historical calculation results."""
from __future__ import annotations

from dataclasses import dataclass

from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_store import ResultRecord, ResultStore


@dataclass(frozen=True)
class ResultAction:
    """One result action already resolved against the active workspace."""

    label: str
    expected_potential: PotentialFileVersion | None = None


@dataclass(frozen=True)
class ResultActionAvailability:
    """Actions that may currently be offered for one historical result."""

    use_state: ResultAction | None = None
    recompute: ResultAction | None = None


def result_action_availability(
    store: ResultStore,
    record: ResultRecord,
    *,
    current_structure_id: int | None,
    current_state_id: int | None,
) -> ResultActionAvailability:
    """Resolve restore/recompute actions for the current workspace state."""
    state = store.state_for_result(record)
    active_state = store.state(current_state_id) if current_state_id is not None else None
    different_state = state is not None and state.id != current_state_id
    different_structure = (
        record.structure_id is not None
        and record.structure_id != current_structure_id
    )

    recorded_potential = state.potential_version if state is not None else None
    current_potential = (
        recorded_potential.current()
        if recorded_potential is not None and recorded_potential.available
        else None
    )
    exact_potential_available = bool(
        current_potential is not None
        and current_potential.available
        and current_potential == recorded_potential
    )
    potential_changed = bool(
        current_potential is not None
        and current_potential.available
        and current_potential != recorded_potential
    )
    snapshot_available = bool(
        state is not None and state.structure_snapshot is not None
    )
    active_has_current_potential = bool(
        potential_changed
        and active_state is not None
        and state is not None
        and active_state.structure_id == state.structure_id
        and active_state.potential_version == current_potential
    )
    can_restore = snapshot_available or exact_potential_available or potential_changed
    can_use = bool(
        state is not None
        and can_restore
        and not active_has_current_potential
        and (different_state or potential_changed)
    )

    use_state = None
    if can_use:
        if potential_changed:
            label = "Continue with current version of this potential"
            expected = current_potential
        elif exact_potential_available and not different_structure:
            label = "Use this potential"
            expected = recorded_potential
        else:
            label = "Use this structure"
            expected = recorded_potential if exact_potential_available else None
        use_state = ResultAction(label, expected)

    can_recompute = bool(
        record.task_name
        and record.task_name != "empty_spheres"
        and record.input_parameters is not None
        and current_structure_id is not None
    )
    recompute = None
    if can_recompute:
        if different_structure:
            label = "Recompute on current structure"
        elif different_state:
            label = "Recompute on current potential"
        else:
            label = "Recompute"
        recompute = ResultAction(label)

    return ResultActionAvailability(use_state=use_state, recompute=recompute)
