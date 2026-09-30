import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/guy4ase-test-matplotlib')

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog
from ase2sprkkr.common.grammar_types import SetOf
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import RelativisticScalingEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def scaling(dialog, name='SOC'):
    tree = dialog.tree_editor.tree
    item, = tree.findItems(name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    return tree.itemWidget(item, 2), item


@pytest.mark.parametrize('task', ['scf', 'bsf'])
@pytest.mark.parametrize('name', ['C', 'SOC'])
def test_expert_uses_same_scaling_widget_and_preserves_type_values(application, task, name):
    parameters = InputParameters.create(task)
    parameters.MODE[name].set({'def': .8, 2: .4})
    original = parameters.to_string(validate=False)
    dialog = InputParametersDialog(parameters)
    parameters = dialog.result()  # Expert edits an isolated copy.
    control, item = scaling(dialog, name)
    assert isinstance(control, RelativisticScalingEditor)
    assert parameters.to_string(validate=False) == original
    assert control.table.rowCount() == 2
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, .6)
    assert parameters.MODE[name](all_values=True) == {'def': .6, 2: .4}
    control.type_index.setValue(5)
    control.add_button.click()
    assert set(parameters.MODE[name](all_values=True)) == {'def', 2, 5}
    assert control.table.rowCount() == 3
    control.table.item(2, 0).setData(Qt.ItemDataRole.EditRole, .2)
    assert parameters.MODE[name](all_values=True)[5] == .2
    control.table.setCurrentCell(1, 0)
    control.remove_button.click()
    assert parameters.MODE[name](all_values=True) == {'def': .6, 5: .2}
    assert item.font(0).bold()
    dialog.close()


def test_invalid_scaling_blocks_expert_accept_and_keeps_draft(application):
    dialog = InputParametersDialog(InputParameters.create('scf'))
    dialog.show()
    control, item = scaling(dialog)
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, 'bad')
    dialog._on_ok()
    assert dialog.isVisible()
    assert control.table.item(0, 0).text() == 'bad'
    assert 'MODE.SOC' in dialog.tree_editor.error_text
    assert dialog.result().MODE.SOC(all_values=True) == {'def': 1.}
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, .5)
    assert not dialog.tree_editor.error_text
    dialog._on_ok()
    assert not dialog.isVisible()
    assert dialog.result().MODE.SOC(all_values=True) == {'def': .5}


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
    assert control.table.rowCount() == 2
    assert control.table.item(0, 0).data(Qt.ItemDataRole.EditRole) == .7
    control.table.item(1, 0).setData(Qt.ItemDataRole.EditRole, .3)
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
    assert isinstance(scaling(dialog)[0], RelativisticScalingEditor)
    dialog.close()


def test_expert_array_scaling_uses_shared_orbital_table(application, monkeypatch):
    parameters = InputParameters.create('scf')
    definition = parameters.MODE.SOC._definition
    monkeypatch.setattr(definition, 'type', SetOf(float, min_length=1))
    monkeypatch.setattr(definition, 'default_value', np.array([1.]))
    parameters.MODE.SOC.set({'def': [1.], 2: [.8, .7, .6]})
    dialog = InputParametersDialog(parameters)
    parameters = dialog.result()  # Expert edits an isolated copy.
    control, item = scaling(dialog)
    assert control.orbital_resolved
    assert [control.table.horizontalHeaderItem(i).text() for i in range(4)] == ['s', 'p', 'd', 'f']
    np.testing.assert_equal(parameters.MODE.SOC(all_values=True)[2], [.8, .7, .6])
    control.table.item(1, 2).setData(Qt.ItemDataRole.EditRole, .3)
    np.testing.assert_equal(dialog.result().MODE.SOC(all_values=True)[2], [.8, .7, .3, .6])
    dialog.close()
