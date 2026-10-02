import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/guy4ase-test-matplotlib')

import numpy as np
import pytest
from ase2sprkkr.common.grammar_types import SetOf
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QToolButton

from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.expert_fields import EXPERT_FIELDS
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import (
    RelativisticScalingEditor,
)
from guy4ase.gui.widgets.input_parameters.modal_editor import (
    ExpertFieldEditorDialog,
)
from guy4ase.gui.widgets.input_parameters.scalar import RealEditor, TextEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def scaling(dialog, name='SOC'):
    tree = dialog.tree_editor.tree
    item, = tree.findItems(name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    return tree.itemWidget(item, 2), item


@pytest.mark.parametrize('task', ['scf', 'bsf'])
@pytest.mark.parametrize('name', ['C', 'SOC'])
def test_expert_scaling_uses_compact_inline_defaultdict_editor(application, task, name):
    parameters = InputParameters.create(task)
    parameters.MODE[name].set({'def': .8, 2: .4})
    original = parameters.to_string(validate=False)
    dialog = InputParametersDialog(parameters)
    parameters = dialog.result()  # Expert edits an isolated copy.
    control, item = scaling(dialog, name)
    assert isinstance(control, RealEditor)
    assert parameters.to_string(validate=False) == original
    assert control.value() == .8
    assert item.child(0).text(0) == '[2]'
    tree_editor = dialog.tree_editor.tree
    assert tree_editor.headerItem().text(3) == ''
    assert tree_editor.headerItem().text(4) == 'Comment'
    type_editor = tree_editor.itemWidget(item.child(0), 2)
    assert isinstance(type_editor, RealEditor)
    assert type_editor.value() == .4
    control.setValue(.6)
    assert parameters.MODE[name](all_values=True) == {'def': .6, 2: .4}
    type_editor.setValue(.3)
    assert parameters.MODE[name](all_values=True) == {'def': .6, 2: .3}
    append_editor = tree_editor.itemWidget(item.child(1), 2)
    assert append_editor.specialValueText() == 'Add value…'
    append_editor.setValue(.2)
    application.processEvents()
    assert parameters.MODE[name](all_values=True) == {'def': .6, 2: .3, 3: .2}
    tree_editor.itemWidget(item.child(0), 3).click()
    application.processEvents()
    assert parameters.MODE[name](all_values=True) == {'def': .6, 3: .2}
    assert isinstance(tree_editor.itemWidget(item, 3), QToolButton)
    assert item.font(0).bold()
    dialog.close()


def test_modal_scaling_add_and_remove_refreshes_its_rows(application):
    parameters = InputParameters.create('scf')
    modal = ExpertFieldEditorDialog(
        parameters,
        ('MODE', 'SOC'),
        EXPERT_FIELDS[('MODE', 'SOC')],
    )
    control = modal.editor
    assert isinstance(control, RelativisticScalingEditor)
    assert control._keys == ['def']

    control.type_index.setValue(1)
    control.add_button.click()
    assert control._keys == ['def', 1]
    assert control.table.currentRow() == 1
    assert modal.value == {'def': 1., 1: 1.}

    row_remove = control.table.cellWidget(1, control._value_columns)
    assert isinstance(row_remove, QToolButton)
    assert row_remove.toolTip() == 'Remove type 1'
    row_remove.click()
    assert control._keys == ['def']
    assert control.table.rowCount() == 1
    assert modal.value == {'def': 1.}
    modal.close()


def test_invalid_modal_scaling_stays_isolated(application, monkeypatch):
    dialog = InputParametersDialog(InputParameters.create('scf'))
    control, item = scaling(dialog)
    assert isinstance(control, RealEditor)

    def reject_invalid(modal):
        assert isinstance(modal.editor, RelativisticScalingEditor)
        modal.editor.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, 'bad')
        modal._accept_if_valid()
        assert modal.result() != QDialog.DialogCode.Accepted
        assert not modal.error_label.isHidden()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ExpertFieldEditorDialog, 'exec', reject_invalid)
    dialog.tree_editor.tree.itemWidget(item, 3).click()
    assert dialog.result().MODE.SOC(all_values=True) == {'def': 1.}
    dialog.close()


def test_text_editor_rebuilds_tree_and_rebinds_scaling(application, monkeypatch):
    dialog = InputParametersDialog(InputParameters.create('scf'))

    def edit(editor):
        editor.editor.setPlainText(editor.editor.toPlainText().replace('NITER=200', 'NITER=135')
                                  + '\nMODE SOC=0.7 SOC2=0.4\n')
        editor.accept()
        assert editor.parameters is not None, editor.error_label.text()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(InputFileEditor, 'exec', edit)
    dialog.edit_input_btn.click()
    assert dialog.result().SCF.NITER() == 135
    control, item = scaling(dialog)
    assert isinstance(control, RealEditor)
    assert control.value() == .7
    assert item.childCount() == 2
    child = dialog.tree_editor.tree.itemWidget(item.child(0), 2)
    assert child.value() == .4
    child.setValue(.3)
    assert dialog.result().MODE.SOC(all_values=True) == {'def': .7, 2: .3}
    dialog.close()


def test_cancel_text_editor_keeps_expert_values(application, monkeypatch):
    dialog = InputParametersDialog(InputParameters.create('scf'))
    before = dialog.result().to_string(validate=False)

    def cancel(editor):
        editor.editor.setPlainText('not an input file')
        editor.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(InputFileEditor, 'exec', cancel)
    dialog.edit_input_btn.click()
    assert dialog.result().to_string(validate=False) == before
    assert isinstance(scaling(dialog)[0], RealEditor)
    dialog.close()


def test_expert_modal_scaling_uses_shared_orbital_table(application, monkeypatch):
    parameters = InputParameters.create('scf')
    definition = parameters.MODE.SOC._definition
    monkeypatch.setattr(definition, 'type', SetOf(float, min_length=1))
    monkeypatch.setattr(definition, 'default_value', np.array([1.]))
    parameters.MODE.SOC.set({'def': [1.], 2: [.8, .7, .6]})
    dialog = InputParametersDialog(parameters)
    parameters = dialog.result()  # Expert edits an isolated copy.
    control, item = scaling(dialog)
    assert isinstance(control, TextEditor)

    def edit(modal):
        full = modal.editor
        assert isinstance(full, RelativisticScalingEditor)
        assert full.orbital_resolved
        assert [full.table.horizontalHeaderItem(i).text() for i in range(4)] == [
            's', 'p', 'd', 'f',
        ]
        full.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, .6)
        full.table.item(1, 2).setData(Qt.ItemDataRole.EditRole, .3)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExpertFieldEditorDialog, 'exec', edit)
    dialog.tree_editor.tree.itemWidget(item, 3).click()
    assert control.text() == '[0.6, 1.0, 1.0, 1.0]'
    np.testing.assert_equal(dialog.result().MODE.SOC(all_values=True)[2], [.8, .7, .3, .6])
    dialog.close()


def test_expert_defaultdict_renders_default_on_parent_and_overrides_as_children(application):
    source = InputParameters.create('xas')
    source.MODE.MDIR.set({'def': [0., 0., 1.], 2: [1., 0., 0.]})
    dialog = InputParametersDialog(source)
    parameters = dialog.result()
    tree = dialog.tree_editor.tree
    item, = tree.findItems(
        'MDIR',
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        0,
    )
    assert 'length 3' in item.text(1)
    parent_editor = tree.itemWidget(item, 2)
    assert isinstance(parent_editor, TextEditor)
    assert parent_editor.text() == '[0.0, 0.0, 1.0]'
    assert item.childCount() == 3
    default_items = item.child(0)
    assert default_items.text(0) == 'Default items'
    assert default_items.childCount() == 3
    assert not default_items.isExpanded()
    assert [default_items.child(index).text(0) for index in range(3)] == [
        '[0]', '[1]', '[2]',
    ]
    override = item.child(1)
    assert override.text(0) == '[2]'
    assert override.childCount() == 3
    assert not override.isExpanded()
    override_editor = tree.itemWidget(override, 2)
    assert isinstance(override_editor, TextEditor)
    assert override_editor.text() == '[1.0, 0.0, 0.0]'
    remove_button = tree.itemWidget(override, 3)
    assert isinstance(remove_button, QToolButton)
    assert remove_button.toolTip() == 'Remove repeated value 2'
    assert item.child(2).text(0) == '[3]'
    assert item.child(2).text(4) == 'Add numbered value'
    assert item.child(2).childCount() == 0
    append_editor = tree.itemWidget(item.child(2), 2)
    assert append_editor.placeholderText() == 'Add value…'

    override_editor.setText('{.25,.5,.75}')
    override_editor.editingFinished.emit()
    application.processEvents()
    np.testing.assert_allclose(parameters.MODE.MDIR(), [0., 0., 1.])
    np.testing.assert_allclose(parameters.MODE.MDIR(all_values=True)[2], [.25, .5, .75])
    assert [
        tree.itemWidget(override.child(index), 2).value()
        for index in range(3)
    ] == [.25, .5, .75]

    tree.itemWidget(override.child(0), 2).setValue(.125)
    application.processEvents()
    np.testing.assert_allclose(
        parameters.MODE.MDIR(all_values=True)[2],
        [.125, .5, .75],
    )
    assert override_editor.text() == '[0.125, 0.5, 0.75]'

    append_editor.setText('{.1,.2,.3}')
    append_editor.editingFinished.emit()
    application.processEvents()
    np.testing.assert_allclose(parameters.MODE.MDIR(all_values=True)[3], [.1, .2, .3])
    assert [item.child(index).text(0) for index in range(4)] == [
        'Default items', '[2]', '[3]', '[4]',
    ]
    assert tree.itemWidget(item.child(3), 2).placeholderText() == 'Add value…'

    tree.itemWidget(item.child(1), 3).click()
    application.processEvents()
    assert 2 not in parameters.MODE.MDIR(all_values=True)
    assert [item.child(index).text(0) for index in range(3)] == [
        'Default items', '[3]', '[4]',
    ]
    dialog.close()


def test_expert_numbered_vectors_render_one_complete_value_per_child(application):
    source = InputParameters.create('bsf')
    source.set({
        'ENERGY': {'NE': [200]},
        'TASK': {
            'KA': [[0., 0., 0.], [1., 0., 0.]],
            'KE': [[1., 0., 0.], [1., 1., 0.]],
        },
    })
    dialog = InputParametersDialog(source)
    parameters = dialog.result()
    tree = dialog.tree_editor.tree
    item, = tree.findItems(
        'KE',
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        0,
    )

    assert item.text(2) == '<2 values>'
    assert [item.child(index).text(0) for index in range(3)] == [
        '[1]', '[2]', '[3]',
    ]
    assert item.child(0).childCount() == 3
    assert not item.child(0).isExpanded()
    assert item.child(2).childCount() == 0
    assert [item.child(0).child(index).text(0) for index in range(3)] == [
        '[0]', '[1]', '[2]',
    ]
    editor = tree.itemWidget(item.child(1), 2)
    assert isinstance(editor, TextEditor)
    assert editor.text() == '[1.0, 1.0, 0.0]'

    editor.setText('{.5,.25,.125}')
    editor.editingFinished.emit()
    application.processEvents()
    np.testing.assert_allclose(parameters.TASK.KE(all_values=True)[1], [.5, .25, .125])
    dialog.close()


def test_clicking_tree_row_after_repeated_edit_keeps_scroll_position(application):
    source = InputParameters.create('xas')
    source.MODE.MDIR.set({'def': [0., 0., 1.], 2: [1., 0., 0.]})
    dialog = InputParametersDialog(source)
    parameters = dialog.result()
    dialog.resize(1000, 650)
    dialog.show()
    application.processEvents()
    tree = dialog.tree_editor.tree
    item, = tree.findItems(
        'MDIR',
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        0,
    )
    tree.scrollToItem(item)
    application.processEvents()
    child = item.child(1)
    editor = tree.itemWidget(child, 2)
    editor.setFocus()
    editor.selectAll()
    QTest.keyClicks(editor, '{.2,.3,.4}')
    application.processEvents()

    section = item.parent()
    section_rect = tree.visualItemRect(section)
    scrollbar = tree.verticalScrollBar()
    position = scrollbar.value()
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(100, section_rect.center().y()),
    )
    application.processEvents()

    assert scrollbar.value() == position
    assert item.child(1) is child
    np.testing.assert_allclose(
        parameters.MODE.MDIR(all_values=True)[2],
        [.2, .3, .4],
    )
    dialog.close()
