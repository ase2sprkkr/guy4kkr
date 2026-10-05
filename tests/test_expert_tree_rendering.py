"""Behavioral coverage for direct recursive Expert QTreeWidget rendering."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from ase2sprkkr.common.grammar_types import Array, Integer, Real, Sequence, Table
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.widgets.input_parameters.scalar import IntegerEditor, RealEditor, TextEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def _row(tree, name, column=0):
    return tree.findItems(
        name,
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        column,
    )[0]


def test_table_cells_render_through_shared_scalar_editors(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    table_type = Table(columns=[Integer(), Real()], header=False)
    monkeypatch.setattr(option._definition, "type", table_type)
    monkeypatch.setattr(option._definition, "grammar_type", table_type)
    option.set(table_type.convert([(1, 2.5), (3, 4.5)]))
    dialog = InputParametersDialog(parameters)
    tree = dialog.tree_editor.tree
    item = dialog.tree_editor._option_rows[("SCF", "NITER")]

    assert item.text(2) == "<Table>"
    assert item.childCount() == 2
    first_row = item.child(0)
    second_row = item.child(1)
    assert isinstance(tree.itemWidget(first_row.child(0), 2), IntegerEditor)
    assert isinstance(tree.itemWidget(first_row.child(1), 2), RealEditor)
    editor = tree.itemWidget(second_row.child(1), 2)
    editor.setValue(8.25)
    assert dialog.session.value(("SCF", "NITER"))[1]["f1"] == 8.25
    assert dialog.session.undo_stack.count() == 1
    dialog.close()


def test_table_structured_2d_imported_shape_keeps_existing_rendering(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    table_type = Table(columns=[Integer(), Real()], header=False)
    monkeypatch.setattr(option._definition, "type", table_type)
    monkeypatch.setattr(option._definition, "grammar_type", table_type)
    option._value = table_type.convert([[1, 2.5], [3, 4.5]])
    dialog = InputParametersDialog(parameters)
    item = dialog.tree_editor._option_rows[("SCF", "NITER")]

    assert item.text(2) == "<Table>"
    assert item.childCount() == 2
    dialog.close()


def test_subtree_rebuild_keeps_dependency_registry_deduplicated(application):
    parameters = InputParameters.create("scf")
    parameters.MODE.SOC.set({"def": 1.0})
    dialog = InputParametersDialog(parameters)
    tree_editor = dialog.tree_editor
    tree = tree_editor.tree
    path = ("MODE", "SOC")

    for value in (0.8, 0.7, 0.6):
        dialog.session.set_value(path, {"def": value, 2: 0.4})
        application.processEvents()
        dialog.session.set_value(path, {"def": value})
        application.processEvents()

    live_editors = [
        editor for _item, editor in tree_editor._editor_widgets()
        if editor is not None
    ]
    assert len(tree_editor._dependency_editors) == len(live_editors)
    assert set(tree_editor._dependency_editors) == {id(editor) for editor in live_editors}
    dialog.close()


def test_removing_invalid_repeated_editor_clears_validation_state(application):
    parameters = InputParameters.create("xas")
    parameters.MODE.MDIR.set({"def": [0.0, 0.0, 1.0], 2: [1.0, 0.0, 0.0]})
    dialog = InputParametersDialog(parameters)
    tree_editor = dialog.tree_editor
    tree = tree_editor.tree
    item = tree_editor._option_rows[("MODE", "MDIR")]
    occurrence = item.child(1)
    editor = tree.itemWidget(occurrence, 2)
    editor.setText("{not valid")
    assert not editor.commit()
    assert tree_editor.has_errors

    tree.itemWidget(occurrence, 3).click()
    application.processEvents()

    assert 2 not in dialog.result().MODE.MDIR(all_values=True)
    assert not tree_editor.has_errors
    assert not tree_editor.error_text
    dialog.close()


def test_tree_array_append_commits_numpy_backed_array_once(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.TAU.CLURAD
    array_type = Array(Real(), min_length=1, max_length=4)
    monkeypatch.setattr(option._definition, "type", array_type)
    monkeypatch.setattr(option._definition, "grammar_type", array_type)
    option.set(np.array([1.5, 2.5]))
    dialog = InputParametersDialog(parameters)
    item = dialog.tree_editor._option_rows[("TAU", "CLURAD")]
    tree = dialog.tree_editor.tree
    append_editor = tree.itemWidget(item.child(2), 2)
    append_editor.setValue(3.5)
    application.processEvents()

    result = dialog.session.value(("TAU", "CLURAD"))
    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, [1.5, 2.5, 3.5])
    assert dialog.session.undo_stack.count() == 1
    dialog.close()


def test_repeated_dict_array_append_can_be_edited_by_components(application):
    parameters = InputParameters.create("xas")
    parameters.MODE.MDIR.set({"def": [0.0, 0.0, 1.0]})
    dialog = InputParametersDialog(parameters)
    tree_editor = dialog.tree_editor
    tree = tree_editor.tree
    path = ("MODE", "MDIR")
    root = tree_editor._option_rows[path]

    append_item = root.child(root.childCount() - 1)
    assert append_item.text(0) == "[1]"
    assert append_item.childCount() == 3
    components = [tree.itemWidget(append_item.child(i), 2) for i in range(3)]
    assert all(isinstance(component, RealEditor) for component in components)

    components[0].setValue(0.25)
    application.processEvents()

    value = dialog.session.value(path)
    assert 1 in value
    np.testing.assert_array_equal(value[1], [0.25, 0.0, 1.0])
    assert dialog.session.undo_stack.count() == 1

    root = tree_editor._option_rows[path]
    assert root.child(root.childCount() - 1).text(0) == "[2]"
    dialog.close()


def test_nested_fixed_array_draft_inside_defaultdict_is_atomic(application, monkeypatch):
    parameters = InputParameters.create("xas")
    option = parameters.MODE.MDIR
    array_type = Array(Real(), length=3)
    monkeypatch.setattr(option._definition, "type", array_type)
    monkeypatch.setattr(option._definition, "grammar_type", array_type)
    option._value = {"def": [0.0, 0.0, 1.0], 2: None}

    class RejectDraftPlugin:
        def apply(self, _before, candidate, _dormant):
            value = candidate.MODE.MDIR(all_values=True).get(2)
            if value is not None and len(value) == 3 and value[2] == 3.0:
                raise RuntimeError("reject nested draft")

    from guy4ase.gui.input_parameters.session import InputParametersSession

    session = InputParametersSession(parameters, plugins=(RejectDraftPlugin(),))
    dialog = InputParametersDialog(session)
    tree = dialog.tree_editor.tree
    item = dialog.tree_editor._option_rows[("MODE", "MDIR")]
    occurrence = item.child(1)
    components = [tree.itemWidget(occurrence.child(i), 2) for i in range(3)]
    initial = np.array(session.value(("MODE", "MDIR"))[2], copy=True)

    components[0].setValue(1.0)
    components[1].setValue(2.0)
    np.testing.assert_array_equal(
        session.value(("MODE", "MDIR"))[2], initial, strict=False
    )
    assert session.undo_stack.count() == 0

    components[2].setValue(3.0)
    np.testing.assert_array_equal(
        session.value(("MODE", "MDIR"))[2], initial, strict=False
    )
    assert session.undo_stack.count() == 0

    components[2].setValue(4.0)
    application.processEvents()
    np.testing.assert_array_equal(session.value(("MODE", "MDIR"))[2], [1.0, 2.0, 4.0])
    assert session.undo_stack.count() == 1
    dialog.close()


def _install_sequence_array(option, monkeypatch, *, repeated=False):
    inner = Array(Real(), min_length=1, max_length=4)
    sequence_type = Sequence(Integer(), inner, names=("count", "values"))
    monkeypatch.setattr(option._definition, "type", sequence_type)
    monkeypatch.setattr(option._definition, "grammar_type", sequence_type)
    return inner, sequence_type


def test_sequence_nested_array_append_updates_rows_and_one_transaction(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    inner, sequence_type = _install_sequence_array(option, monkeypatch)
    option.set(sequence_type.convert([1, np.array([2.0])]))
    dialog = InputParametersDialog(parameters)
    path = ("SCF", "NITER")
    item = dialog.tree_editor._option_rows[path]
    array_item = item.child(1)
    existing_editor = dialog.tree_editor.tree.itemWidget(array_item.child(0), 2)
    assert isinstance(existing_editor, RealEditor)
    append_editor = dialog.tree_editor.tree.itemWidget(array_item.child(1), 2)

    append_editor.setValue(3.0)
    application.processEvents()

    result = dialog.session.value(path)
    assert isinstance(result, sequence_type.value_type)
    assert result.count == 1
    np.testing.assert_array_equal(result.values, [2.0, 3.0])
    item = dialog.tree_editor._option_rows[path]
    array_item = item.child(1)
    assert array_item.childCount() == 3
    assert dialog.session.undo_stack.count() == 1
    dialog.close()


def test_nested_scalar_change_preserves_existing_editor_widget(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.NITER
    _inner, sequence_type = _install_sequence_array(option, monkeypatch)
    option.set(sequence_type.convert([1, np.array([2.0])]))
    dialog = InputParametersDialog(parameters)
    item = dialog.tree_editor._option_rows[("SCF", "NITER")]
    array_item = item.child(1)
    leaf = dialog.tree_editor.tree.itemWidget(array_item.child(0), 2)

    leaf.setValue(4.0)
    application.processEvents()

    assert dialog.tree_editor.tree.itemWidget(array_item.child(0), 2) is leaf
    assert dialog.session.value(("SCF", "NITER")).values[0] == 4.0
    dialog.close()


def test_repeated_sequence_nested_array_append_refreshes_occurrence(application, monkeypatch):
    parameters = InputParameters.create("xas")
    option = parameters.MODE.MDIR
    inner, sequence_type = _install_sequence_array(option, monkeypatch, repeated=True)
    option.set({
        "def": sequence_type.convert([1, np.array([0.0])]),
        2: sequence_type.convert([2, np.array([2.0])]),
    })
    dialog = InputParametersDialog(parameters)
    path = ("MODE", "MDIR")
    root = dialog.tree_editor._option_rows[path]
    occurrence = root.child(2)
    array_row = occurrence.child(1)
    append_editor = dialog.tree_editor.tree.itemWidget(array_row.child(1), 2)

    append_editor.setValue(3.0)
    application.processEvents()

    value = dialog.session.value(path)[2]
    assert isinstance(value, sequence_type.value_type)
    np.testing.assert_array_equal(value.values, [2.0, 3.0])
    root = dialog.tree_editor._option_rows[path]
    occurrence = root.child(2)
    array_row = occurrence.child(1)
    assert array_row.childCount() == 3
    assert dialog.session.undo_stack.count() == 1
    dialog.close()


def test_composite_fixed_array_draft_components_are_leaf_editors(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.TAU.CLURAD
    child_type = Sequence(Integer(), Real(), names=("count", "energy"))
    outer_type = Array(child_type, length=2)
    monkeypatch.setattr(option._definition, "type", outer_type)
    monkeypatch.setattr(option._definition, "grammar_type", outer_type)
    dialog = InputParametersDialog(parameters)
    path = ("TAU", "CLURAD")
    item = dialog.tree_editor._option_rows[path]
    tree = dialog.tree_editor.tree
    components = [tree.itemWidget(item.child(index), 2) for index in range(2)]

    assert all(isinstance(component, TextEditor) for component in components)
    assert all(item.child(index).childCount() == 0 for index in range(2))
    components[0].setText("(1, 2.0)")
    assert components[0].commit()
    assert dialog.session.value(path) is None
    components[1].setText("(3, 4.0)")
    assert components[1].commit()

    result = dialog.session.value(path)
    assert len(result) == 2
    assert result[0].count == 1 and result[0].energy == 2.0
    assert result[1].count == 3 and result[1].energy == 4.0
    assert dialog.session.undo_stack.count() == 1
    dialog.close()
