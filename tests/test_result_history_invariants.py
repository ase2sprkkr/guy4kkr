from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application import workspace_controller as controller_module
from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.workspace import Generation
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


class _Parameters:
    def __init__(self, task_name="dos", value=1):
        self.task_name = task_name
        self.value = value


def _captured_result(task="dos", parameters=None):
    return capture_result(
        SimpleNamespace(task_name=task),
        input_parameters=parameters,
        output_path=None,
        potential_path=None,
    )


def _add_structure(history: ResultHistory, symbol: str = "Fe"):
    return history.add_structure_state(
        capture_structure(Atoms(symbol), potential_path=None)
    )


def _assert_result_edges_exist(history: ResultHistory) -> None:
    result_ids = {record.id for record in history.results}
    for structure in history.structures:
        del structure  # structure enumeration is part of the public aggregate contract
    for record in history.results:
        state = history.state_for_result(record)
        if state is None:
            continue
        if state.produced_by_result_id is not None:
            assert state.produced_by_result_id in result_ids
        if state.potential_source_result_id is not None:
            assert state.potential_source_result_id in result_ids


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


@pytest.mark.parametrize(
    ("structure_id", "input_state_id"),
    ((1, None), (None, 1)),
)
def test_add_result_rejects_partial_provenance(structure_id, input_state_id):
    history = ResultHistory()

    with pytest.raises(ValueError, match="requires structure_id and input_state_id together"):
        history.add_result(
            _captured_result(),
            structure_id=structure_id,
            input_state_id=input_state_id,
            directory=None,
        )

    assert len(history) == 0


def test_add_result_rejects_cross_structure_input_state_atomically():
    history = ResultHistory()
    first_structure, _ = _add_structure(history, "Fe")
    second_structure, second_state = _add_structure(history, "Cu")
    captured = _captured_result()

    with pytest.raises(AssertionError, match="Result provenance mismatch"):
        history.add_result(
            captured,
            structure_id=first_structure,
            input_state_id=second_state,
            directory=None,
        )

    assert len(history) == 0
    assert history.results_for_state(second_state) == ()

    record = history.add_result(
        captured,
        structure_id=second_structure,
        input_state_id=second_state,
        directory=None,
    )
    assert record.id == 1


def test_prepared_output_state_and_result_commit_together():
    history = ResultHistory()
    structure_id, state_id = _add_structure(history)
    output = capture_structure(Atoms("Fe"), potential_path=None)

    record = history.add_result(
        _captured_result("scf"),
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
        output_structure=output,
    )

    assert record.id == 1
    assert record.output_state_id == state_id + 1
    state = history.state(record.output_state_id)
    assert state.produced_by_result_id == record.id
    assert history.result(record.id) is record
    _assert_result_edges_exist(history)


def test_state_result_edges_can_only_be_created_by_atomic_result_commit():
    history = ResultHistory()
    _structure_id, state_id = _add_structure(history)

    with pytest.raises(TypeError):
        history.add_child_state(state_id, produced_by_result_id=999)
    with pytest.raises(TypeError):
        history.add_child_state(state_id, potential_source_result_id=999)

    state = history.state(state_id)
    assert state.produced_by_result_id is None
    assert state.potential_source_result_id is None


def test_captured_potential_path_is_canonical(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    potential = directory / "Fe.pot"
    potential.write_text("potential", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    captured = capture_structure(Atoms("Fe"), potential_path=Path("run/Fe.pot"))

    assert captured.potential_path == potential.resolve()
    assert captured.potential_version is not None
    assert captured.potential_version.path == potential.resolve()


def test_capture_failure_happens_before_history_mutation(monkeypatch):
    history = ResultHistory()
    structure_id, state_id = _add_structure(history)

    def fail_snapshot(_parameters):
        raise ValueError("parameter snapshot failed")

    monkeypatch.setattr(
        "guy4ase.gui.application.result_capture.snapshot_input_parameters",
        fail_snapshot,
    )
    with pytest.raises(ValueError, match="parameter snapshot failed"):
        capture_result(
            SimpleNamespace(task_name="scf"),
            input_parameters=object(),
            output_path=None,
            potential_path=None,
        )

    assert len(history) == 0
    assert history.results_for_state(state_id) == ()
    record = history.add_result(
        _captured_result("scf"),
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )
    assert record.id == 1


def test_replace_structure_history_failure_keeps_workspace_unchanged(monkeypatch):
    controller = WorkspaceController()
    original = Atoms("Fe")
    controller.replace_structure(original, directory="old", restarted=True)
    original_structure_id = controller.structure_id
    original_state_id = controller.state_id
    original_generation = controller.generation

    def fail_add_structure_state(*_args, **_kwargs):
        raise ValueError("state preparation failed")

    monkeypatch.setattr(
        controller.result_history,
        "add_structure_state",
        fail_add_structure_state,
    )

    with pytest.raises(ValueError, match="state preparation failed"):
        controller.replace_structure(Atoms("Cu"), directory="new", restarted=False)

    assert controller.atoms is original
    assert controller.directory == "old"
    assert controller.structure_id == original_structure_id
    assert controller.state_id == original_state_id
    assert controller.restarted is True
    assert controller.generation == original_generation


def test_replace_structure_capture_failure_keeps_workspace_and_history_unchanged(
    monkeypatch,
):
    controller = WorkspaceController()
    original = Atoms("Fe")
    controller.replace_structure(original, directory="old")
    history_size = len(controller.result_history.structures)
    generation = controller.generation

    def fail_capture(*_args, **_kwargs):
        raise ValueError("structure snapshot failed")

    monkeypatch.setattr(controller_module, "capture_structure", fail_capture)
    with pytest.raises(ValueError, match="structure snapshot failed"):
        controller.replace_structure(Atoms("Cu"), directory="new")

    assert controller.atoms is original
    assert controller.directory == "old"
    assert controller.generation == generation
    assert len(controller.result_history.structures) == history_size


def test_apply_structure_edit_history_failure_keeps_workspace_unchanged(monkeypatch):
    controller = WorkspaceController()
    original = Atoms("Fe")
    controller.replace_structure(original)
    original_structure_id = controller.structure_id
    original_state_id = controller.state_id
    original_generation = controller.generation

    def fail_add_structure_state(*_args, **_kwargs):
        raise ValueError("state preparation failed")

    monkeypatch.setattr(
        controller.result_history,
        "add_structure_state",
        fail_add_structure_state,
    )

    with pytest.raises(ValueError, match="state preparation failed"):
        controller.apply_structure_edit(
            lambda atoms: atoms,
            expected_generation=original_generation,
        )

    assert controller.atoms is original
    assert controller.structure_id == original_structure_id
    assert controller.state_id == original_state_id
    assert controller.restarted is False
    assert controller.generation == original_generation


def test_result_capture_detaches_task_and_generic_parameters():
    parameters = _Parameters(task_name="dos", value=7)
    result = SimpleNamespace(task_name=parameters.task_name)
    captured = capture_result(
        result,
        input_parameters=parameters,
        output_path=None,
        potential_path=None,
    )

    parameters.task_name = "jxc"
    parameters.value = 99
    result.task_name = "arpes"

    assert captured.task_name == "dos"
    assert captured.input_parameters is not parameters
    assert captured.input_parameters.task_name == "dos"
    assert captured.input_parameters.value == 7


def test_result_capture_deep_copies_mapping_parameters():
    parameters = {"mesh": [10, 20, 30]}
    captured = capture_result(
        SimpleNamespace(task_name="empty-spheres"),
        input_parameters=parameters,
        output_path=None,
        potential_path=None,
    )

    parameters["mesh"][0] = 999
    assert captured.input_parameters == {"mesh": [10, 20, 30]}
