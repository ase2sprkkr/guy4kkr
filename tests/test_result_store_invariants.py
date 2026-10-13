from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace import Generation
from guy4ase.gui.application.workspace_controller import CalculationRequest


def test_calculation_request_requires_structure_and_state_ids():
    common = dict(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=".",
        generation=Generation(),
    )

    with pytest.raises(TypeError, match="structure_id"):
        CalculationRequest(**common, state_id=1)
    with pytest.raises(TypeError, match="state_id"):
        CalculationRequest(**common, structure_id=1)


def test_add_result_rejects_cross_structure_input_state_atomically():
    store = ResultStore()
    first_structure, _first_state = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    second_structure, second_state = store.new_structure_state(
        Atoms("Cu"), potential_path=None
    )
    result = SimpleNamespace(task_name="dos")

    with pytest.raises(AssertionError, match="Result provenance mismatch"):
        store.add_result(
            result,
            structure_id=first_structure,
            input_state_id=second_state,
            atoms=Atoms("Cu"),
            input_parameters=None,
            directory=None,
        )

    assert len(store) == 0
    assert store.results_for_state(second_state) == ()

    record = store.add_result(
        result,
        structure_id=second_structure,
        input_state_id=second_state,
        atoms=Atoms("Cu"),
        input_parameters=None,
        directory=None,
    )
    assert record.id == 1
