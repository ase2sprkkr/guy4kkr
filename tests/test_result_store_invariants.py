from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace import Generation
from guy4ase.gui.application.workspace_controller import CalculationRequest


class _Parameters:
    def __init__(self, task_name="dos", value=1):
        self.task_name = task_name
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.task_name, self.value)


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


def test_result_record_snapshots_task_name_and_input_parameters():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    parameters = _Parameters(task_name="dos", value=7)
    result = SimpleNamespace(task_name=parameters.task_name)

    record = store.add_result(
        result,
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters=parameters,
        directory=None,
    )

    assert record.task_name == "dos"
    assert record.input_parameters is not parameters
    assert record.input_parameters.task_name == "dos"
    assert record.input_parameters.value == 7

    parameters.task_name = "jxc"
    parameters.value = 99
    result.task_name = "arpes"

    assert record.task_name == "dos"
    assert record.input_parameters.task_name == "dos"
    assert record.input_parameters.value == 7


def test_result_record_deep_copies_generic_mapping_parameters():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    parameters = {"mesh": [10, 20, 30]}

    record = store.add_result(
        SimpleNamespace(task_name="empty-spheres"),
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters=parameters,
        directory=None,
    )

    parameters["mesh"][0] = 999

    assert record.input_parameters == {"mesh": [10, 20, 30]}
