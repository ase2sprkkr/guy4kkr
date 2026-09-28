"""Data integrity and validation regressions found in the GUI review."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/guy4ase-test-matplotlib')

from dataclasses import replace

import numpy as np
import pytest
from ase import Atoms
from ase2sprkkr.common.warnings import DataValidityError
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from guy4ase.gui.dialogs import main_window
from guy4ase.gui.dialogs.expert_input import InputParametersDialog
from guy4ase.gui.dialogs.guided_input import (
    GuidedInputParametersDialog,
    _prepare_parameters,
)
from guy4ase.gui.input_parameters.specs import bsf, scf
from guy4ase.gui.input_parameters.validation import validate_setup


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def tree_editor(dialog, name):
    item, = dialog._tree.findItems(name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    return item, dialog._tree.itemWidget(item, 2)


@pytest.mark.parametrize('path,value', [(('SCF', 'MIX'), .1234567), (('SCF', 'NITER'), 5000)])
def test_focus_without_edit_preserves_raw_numeric_value(app, path, value):
    p = InputParameters.create('scf')
    p[path[0]][path[1]].set(value)
    d = GuidedInputParametersDialog('scf', p)
    editor = d.editors_for(path)[-1]
    d.select_page(editor.page_id)
    d.show()
    editor.control.setFocus()
    app.processEvents()
    d.directory_edit.setFocus()
    app.processEvents()
    assert editor.commit()
    assert d.session.value(path) == value
    assert d.session.undo_stack.count() == 0
    d.close()


def test_multi_valued_cutoffs_are_visible_and_preserved(app):
    p = InputParameters.create('dos')
    p.SITES.NL = [3, 4]
    d = GuidedInputParametersDialog('dos', p)
    editor = d.editors_for(('SITES', 'NL'))[0]
    assert editor.control.text() == '[3, 4]'
    assert editor.commit()
    np.testing.assert_array_equal(d.session.value(('SITES', 'NL')), [3, 4])
    assert d.session.undo_stack.count() == 0
    editor.control.setText('[3, 5]')
    assert editor.commit()
    np.testing.assert_array_equal(d.session.value(('SITES', 'NL')), [3, 5])
    d.session.undo_stack.undo()
    np.testing.assert_array_equal(d.session.value(('SITES', 'NL')), [3, 4])
    d.close()


@pytest.mark.parametrize('task,path', [('arpes', ('SPEC_EL', name)) for name in ('THETA', 'NT', 'NP')]
                         + [('xas', ('TASK', 'FRAMETET'))])
def test_implicit_controls_show_backend_defaults_as_placeholders(app, task, path):
    d = GuidedInputParametersDialog(task, InputParameters.create(task))
    editor = d.editors_for(path)[0]
    option = d.session.option(path)
    assert not option.is_set()
    text_input = editor.control.lineEdit() if hasattr(editor.control, 'lineEdit') else editor.control
    assert text_input.text() == ''
    assert text_input.placeholderText().startswith('Default: ')
    assert editor.commit()
    assert not d.session.is_modified()
    d.close()


@pytest.mark.parametrize('expert', [False, True])
def test_default_placeholder_focus_and_clear_do_not_materialize_defaults(app, expert):
    p = InputParameters.create('scf')
    before = p.to_string(validate=False)
    d = InputParametersDialog(p) if expert else GuidedInputParametersDialog('scf', p)
    if expert:
        _, control = tree_editor(d, 'MIX')
        current = d.result
    else:
        editor = d.editors_for(('SCF', 'MIX'))[0]
        d.select_page(editor.page_id)
        control = editor.control
        current = d.session.result
    d.show()
    control.setFocus()
    app.processEvents()
    assert control.lineEdit().text() == ''
    assert control.lineEdit().placeholderText() == 'Default: 0.2'
    control.clearFocus()
    app.processEvents()
    assert not current().SCF.MIX.is_set()
    assert current().to_string(validate=False) == before
    control.setValue(.3)
    control.editingFinished.emit()
    assert current().SCF.MIX() == .3
    control.clear()
    control.editingFinished.emit()
    assert current().SCF.MIX() == .2
    assert not current().SCF.MIX.is_set()
    assert control.lineEdit().placeholderText() == 'Default: 0.2'
    assert control.lineEdit().text() == ''
    d.close()


def test_arpes_default_energy_placeholder_follows_display_units(app):
    d = GuidedInputParametersDialog('arpes', InputParameters.create('arpes'))
    editor = d.editors_for(('ENERGY', 'EMIN'))[-1].control
    assert editor.number.lineEdit().text() == ''
    assert editor.number.lineEdit().placeholderText() == 'Default: -8'
    editor.units.setCurrentText('Ry')
    assert editor.number.lineEdit().text() == ''
    assert editor.number.lineEdit().placeholderText() != 'Default: -8'
    assert editor.commit()
    assert not d.session.option(('ENERGY', 'EMINEV')).is_set()
    assert not d.session.is_modified()
    d.close()


@pytest.mark.parametrize('expert', [False, True])
def test_typing_over_numeric_default_placeholder(app, expert):
    p = InputParameters.create('scf')
    d = InputParametersDialog(p) if expert else GuidedInputParametersDialog('scf', p)
    if expert:
        item, control = tree_editor(d, 'MIX')
        d._tree.scrollToItem(item)
        current = d.result
    else:
        editor = d.editors_for(('SCF', 'MIX'))[0]
        d.select_page(editor.page_id)
        control = editor.control
        current = d.session.result
    d.show()
    control.setFocus()
    app.processEvents()
    QTest.keyClicks(control, control.locale().toString(.35, 'f', 2))
    QTest.keyClick(control, Qt.Key.Key_Tab)
    app.processEvents()
    assert current().SCF.MIX() == .35
    d.close()


@pytest.mark.parametrize('expert', [False, True])
def test_scf_cannot_select_unsupported_relative_bound(app, expert):
    p = InputParameters.create('scf')
    d = InputParametersDialog(p) if expert else GuidedInputParametersDialog('scf', p)
    editor = tree_editor(d, 'EMIN / EMINEV')[1] if expert else d.editors_for(('ENERGY', 'EMIN'))[0].control
    assert not editor.relative.isEnabled()
    assert not editor.relative.isChecked()
    assert 'absolute' in editor.relative.toolTip()
    d.close()


@pytest.mark.parametrize('task', ['dos', 'bsf', 'arpes'])
def test_reference_switch_changes_both_bounds_atomically(app, task):
    p = InputParameters.create(task)
    if task == 'bsf':
        p.ENERGY.NE = [200]
    d = GuidedInputParametersDialog(task, p)
    editor = d.editors_for(('ENERGY', 'EMIN'))[-1].control
    target = not editor.relative.isChecked()
    editor.relative.setChecked(target)
    for name in ('EMIN', 'EMAX'):
        assert (d.session.value(('ENERGY', name + 'EV')) is not None) == target
        assert d.editors_for(('ENERGY', name))[-1].control.relative.isChecked() == target
    assert d.session.undo_stack.count() == 1
    d.session.undo_stack.undo()
    assert not d.session.is_modified()
    d.close()


@pytest.mark.parametrize('task', ['scf', 'dos', 'bsf'])
def test_backend_rejects_relative_bounds_that_sprkkr_would_ignore(task):
    p = InputParameters.create(task)
    p.CONTROL.POTFIL = 'Fe.pot'
    if task == 'bsf':
        p.set({'ENERGY': {'NE': [200]}, 'TASK': {'KPATH': 1}})
    p.ENERGY.EMINEV = -3.
    with pytest.raises(ValueError, match='supplied together'):
        validate_setup(p)
    with pytest.raises(DataValidityError, match='supplied together'):
        p.validate('save')


@pytest.mark.parametrize('updates', [{'THETA': [-20., 20.]}, {'NT': 200}])
def test_incomplete_arpes_scan_rejected_by_gui_and_backend(updates):
    p = InputParameters.create('arpes')
    p.CONTROL.POTFIL = 'Fe.pot'
    p.SPEC_EL.set(updates)
    with pytest.raises(ValueError, match='consistent angular scan'):
        validate_setup(p)
    with pytest.raises(DataValidityError, match='consistent angular scan'):
        p.validate('save')
    p.SPEC_EL.set({'THETA': [-20., 20.], 'NT': 200})
    validate_setup(p)
    p.validate('save')


def test_invalid_expert_text_blocks_ok_until_corrected(app):
    d = InputParametersDialog(InputParameters.create('scf'))
    _, editor = tree_editor(d, 'MDIR')
    editor.setText('garbage')
    editor.editingFinished.emit()
    assert editor.input_commit.error
    d._on_ok()
    assert QDialog.result(d) != QDialog.DialogCode.Accepted
    assert d.result().MODE.MDIR() is None
    editor.setText('{0,0,1}')
    editor.editingFinished.emit()
    d._on_ok()
    assert QDialog.result(d) == QDialog.DialogCode.Accepted
    d.close()


def test_expert_numeric_error_is_inline_and_keeps_model(app):
    p = InputParameters.create('bsf')
    p.set({'ENERGY': {'NE': [200]}, 'TASK': {
        'KA': [[0., 0., 0.], [1., 0., 0.]], 'KE': [[1., 0., 0.], [1., 1., 0.]]}})
    d = InputParametersDialog(p)
    item, _ = tree_editor(d, 'NE')
    editor = d._tree.itemWidget(item.child(0), 2)
    editor.setValue(1)
    assert editor.input_commit.error
    assert d.result().ENERGY.NE()[0] == 200
    d._on_ok()
    assert QDialog.result(d) != QDialog.DialogCode.Accepted
    editor.setValue(200)
    assert not editor.input_commit.error
    d.close()


def test_expert_cancel_is_isolated(app):
    p = InputParameters.create('scf')
    before = p.to_string(validate=False)
    d = InputParametersDialog(p)
    _, editor = tree_editor(d, 'MIX')
    editor.setValue(.37)
    assert d.result().SCF.MIX() == .37
    assert p.to_string(validate=False) == before
    d.reject()
    assert p.to_string(validate=False) == before


@pytest.mark.parametrize('accept', [False, True])
def test_preview_edits_current_task_not_fresh_scf(app, monkeypatch, accept):
    window = main_window.MainWindow()
    p = InputParameters.create('dos')
    p.SITES.NL = [3, 4]
    window.set_input_parameters(p)
    result = p.copy(copy_values=True)
    result.ENERGY.NE = [42]
    def edit(current, **kwargs):
        assert current is p
        return result if accept else None
    monkeypatch.setattr(main_window, 'edit_input_parameters', edit)
    window._on_input_preview_double_click(None)
    assert window.workspace.input_parameters is (result if accept else p)
    assert window.workspace.input_parameters.task_name.lower() == 'dos'
    window.close()


def test_corrupt_recent_history_is_ignored(app, monkeypatch, tmp_path):
    window = main_window.MainWindow()
    history = tmp_path / 'recent_files.json'
    history.write_text('{not valid JSON', encoding='utf-8')
    monkeypatch.setattr(window, '_recent_files_path', lambda: history)
    window._recent_files = {'structure': [], 'input': [], 'output': []}
    window._last_recent_kind = None

    window._load_recent_files()

    assert window.recent_files == {
        'structure': (), 'input': (), 'output': (),
    }
    assert window.last_recent_kind is None
    window.close()


def test_reset_workspace_clears_the_document_and_views(app):
    window = main_window.MainWindow()
    window.workspace.atoms = Atoms('Fe', cell=(2.8, 2.8, 2.8), pbc=True)
    window.workspace.input_parameters = InputParameters.create('scf')
    window.workspace.directory = '/tmp/calculation'
    window.workspace.potential_path = '/tmp/potential'
    window.workspace.result = object()

    window.reset_workspace()

    assert window.workspace.atoms is None
    assert window.workspace.input_parameters is None
    assert window.workspace.directory is None
    assert window.workspace.potential_path is None
    assert window.workspace.result is None
    window.close()


@pytest.mark.parametrize('task', ['scf', 'dos'])
def test_bsf_import_rejects_another_task_before_normalizing(task):
    with pytest.raises(ValueError, match='Expected BSF'):
        _prepare_parameters(InputParameters.create(task), 'bsf')


def test_unrelated_edit_preserves_invalid_kpath_draft_but_undo_discards_it(app):
    p = InputParameters.create('bsf')
    p.set({'ENERGY': {'NE': [200]}, 'TASK': {'KA': [[0., 0., 0.]], 'KE': [[1., 1., 1.]]}})
    d = GuidedInputParametersDialog('bsf', p)
    editor = d.editors_for(('TASK', 'KA'))[0]
    editor.control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, 'bad')
    assert ('TASK', 'KA') in d._errors
    d.session.set_value(('CONTROL', 'PRINT'), 1)
    assert editor.control.table.item(0, 0).text() == 'bad'
    assert ('TASK', 'KA') in d._errors
    d.session.undo_stack.undo()
    assert not editor._error
    assert editor.control.table.item(0, 0).data(Qt.ItemDataRole.EditRole) == 0.
    d.close()


def test_bsf_group_builders_do_not_depend_on_scf_spec(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("BSF must not build the SCF spec")

    monkeypatch.setattr(scf, 'build_spec', fail_if_called)
    spec = bsf.build_spec()
    ids = {group.id for page in spec.pages for group in page.groups}
    assert {'magnetism', 'orientation', 'beyond_dft', 'scaling', 'cpa'} <= ids
    spec.primary_pages()
