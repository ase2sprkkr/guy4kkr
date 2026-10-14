from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.result_presentation import present_result_tree


class _Value:
    info = ""

    def __init__(self, name):
        self.display_name = name

    def value_label(self):
        return self.display_name

    def actions(self):
        return ()


def _ui_result(task, name):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{name}.out",
        output_values={"value": _Value(name)},
    )


def _captured(result):
    return capture_result(
        result,
        input_parameters=None,
        output_path=None,
        potential_path=None,
    )


def _model(history, structure_id=None, state_id=None, selected_result_id=None):
    return present_result_tree(
        history,
        current_structure_id=structure_id,
        current_state_id=state_id,
        selected_result_id=selected_result_id,
    )


def test_result_projection_groups_by_formula_and_selects_latest_result():
    history = ResultHistory()
    structure_id, state_id = history.add_structure_state(
        capture_structure(Atoms("Fe"), potential_path=None)
    )
    older_record = history.add_result(
        _captured(_ui_result("dos", "old")),
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )
    newest_record = history.add_result(
        _captured(_ui_result("jxc", "new")),
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )

    model = _model(history, structure_id, state_id)

    assert len(model.roots) == 1
    structure = model.roots[0]
    assert structure.label == "Fe"
    assert [child.result_id for child in structure.children] == [
        older_record.id,
        newest_record.id,
    ]
    assert model.selected_result_id == newest_record.id
    assert model.selected is not None
    assert model.selected.values[0].name == "new"

    selected = _model(
        history,
        structure_id,
        state_id,
        selected_result_id=older_record.id,
    )
    assert selected.selected_result_id == older_record.id
    assert selected.selected is not None
    assert selected.selected.values[0].name == "old"


def test_result_projection_hides_internal_branch_nodes():
    history = ResultHistory()
    structure_id, root_state = history.add_structure_state(
        capture_structure(Atoms("Fe"), potential_path=None)
    )

    output_a = capture_structure(Atoms("Fe"), potential_path=None)
    first = history.add_result(
        _captured(_ui_result("scf", "a")),
        structure_id=structure_id,
        input_state_id=root_state,
        directory=None,
        output_structure=output_a,
    )
    output_b = capture_structure(Atoms("Fe"), potential_path=None)
    second = history.add_result(
        _captured(_ui_result("scf", "b")),
        structure_id=structure_id,
        input_state_id=root_state,
        directory=None,
        output_structure=output_b,
    )

    assert history.branch_id_for_result(first) != history.branch_id_for_result(second)

    model = _model(history)
    assert len(model.roots) == 1
    structure = model.roots[0]
    assert [child.result_id for child in structure.children] == [first.id, second.id]
    assert all(not child.label.startswith("Branch") for child in structure.children)
