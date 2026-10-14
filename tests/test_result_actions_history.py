from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.result_presentation import present_result_tree
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


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


def test_result_selector_groups_by_formula_and_switches_displayed_result():
    _application = QApplication.instance() or QApplication([])
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
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_model(_model(history, structure_id, state_id))

    assert widget._selector.topLevelItemCount() == 1
    structure = widget._selector.topLevelItem(0)
    assert structure.text(0) == "Fe"
    assert structure.childCount() == 2
    assert widget.selected_result_id == newest_record.id
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "new"

    widget.set_model(
        _model(history, structure_id, state_id, selected_result_id=older_record.id)
    )
    assert widget.selected_result_id == older_record.id
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "old"
    widget.close()


def test_result_selector_does_not_expose_internal_branch_nodes():
    _application = QApplication.instance() or QApplication([])
    history = ResultHistory()
    structure_id, root_state = history.add_structure_state(
        capture_structure(Atoms("Fe"), potential_path="p0")
    )

    output_a = capture_structure(Atoms("Fe"), potential_path="pa")
    first = history.add_result(
        _captured(_ui_result("scf", "a")),
        structure_id=structure_id,
        input_state_id=root_state,
        directory=None,
        output_structure_snapshot=output_a.structure_snapshot,
        output_potential_path=output_a.potential_path,
        output_potential_version=output_a.potential_version,
    )
    output_b = capture_structure(Atoms("Fe"), potential_path="pb")
    second = history.add_result(
        _captured(_ui_result("scf", "b")),
        structure_id=structure_id,
        input_state_id=root_state,
        directory=None,
        output_structure_snapshot=output_b.structure_snapshot,
        output_potential_path=output_b.potential_path,
        output_potential_version=output_b.potential_version,
    )

    assert history.branch_id_for_result(first) != history.branch_id_for_result(second)

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_model(_model(history))
    structure = widget._selector.topLevelItem(0)
    assert structure.childCount() == 2
    assert all(
        not structure.child(index).text(0).startswith("Branch")
        for index in range(structure.childCount())
    )
    widget.close()
