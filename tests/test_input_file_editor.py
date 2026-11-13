import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_ok_parses_text_and_cancel_leaves_original_unchanged(application):
    parameters = InputParameters.create("scf")
    editor = InputFileEditor(parameters)
    editor.editor.setPlainText(editor.editor.toPlainText().replace("NITER=200", "NITER=135"))
    editor.accept()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert editor.parameters.SCF.NITER() == 135
    assert parameters.SCF.NITER() == 200
    editor = InputFileEditor(parameters)
    editor.editor.setPlainText("garbage")
    editor.reject()
    assert editor.parameters is None
    assert parameters.SCF.NITER() == 200


def test_parse_error_highlights_suspected_line_and_keeps_draft(application):
    parameters = InputParameters.create("scf")
    editor = InputFileEditor(parameters)
    editor.show()
    source = editor.editor.toPlainText().replace("NITER=200", "NITER=invalid")
    expected_line = next(i for i, line in enumerate(source.splitlines(), 1) if "NITER=invalid" in line)
    editor.editor.setPlainText(source)
    editor.accept()
    assert editor.isVisible()
    assert editor.parameters is None
    assert editor.error_line == expected_line
    assert editor.editor.extraSelections()[0].cursor.blockNumber() == expected_line - 1
    assert "Suspected location" in editor.error_label.text()
    assert editor.editor.toPlainText() == source
    assert parameters.SCF.NITER() == 200
    editor.editor.setPlainText(source.replace("NITER=invalid", "NITER=135"))
    assert not editor.editor.extraSelections()
    editor.accept()
    assert editor.parameters.SCF.NITER() == 135


def test_different_task_is_rejected(application):
    editor = InputFileEditor(InputParameters.create("scf"))
    editor.editor.setPlainText(InputParameters.create("dos").to_string(validate=False))
    editor.accept()
    assert editor.parameters is None
    assert editor.error_label.text()


def test_text_edit_is_one_undoable_session_change(application, monkeypatch):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))

    def edit(editor):
        source = editor.editor.toPlainText().replace("NITER=200", "NITER=135").replace("NKTAB=250", "NKTAB=500")
        editor.editor.setPlainText(source)
        editor.accept()
        return editor.result()

    monkeypatch.setattr(InputFileEditor, "exec", edit)
    dialog.edit_input_button.click()
    assert dialog.session.undo_stack.count() == 1
    assert dialog.session.value(("SCF", "NITER")) == 135
    assert dialog.session.value(("TAU", "NKTAB")) == 500
    dialog.undo_button.click()
    assert not dialog.session.is_modified()
    dialog.redo_button.click()
    assert dialog.session.value(("SCF", "NITER")) == 135
    dialog.close()


def test_cancel_does_not_add_history(application, monkeypatch):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    monkeypatch.setattr(InputFileEditor, "exec", lambda editor: QDialog.DialogCode.Rejected)
    dialog.edit_input_button.click()
    assert dialog.session.undo_stack.count() == 0
    assert not dialog.session.is_modified()
    dialog.close()


def test_apply_error_keeps_editor_open_and_highlights_unknown_option(application):
    parameters = InputParameters.create('scf')

    def apply(candidate):
        # The input grammar permits custom names; a consumer can reject them
        # later. That failure must still happen inside the text editor.
        if 'NITERR' in candidate.SCF:
            raise ValueError("The option 'SCF.NITERR' is not known")

    editor = InputFileEditor(parameters, apply_parameters=apply)
    source = editor.editor.toPlainText().replace('NITER=200', 'NITER=200\n\tNITERR=135')
    # A comment and the same name in another section must not win the match.
    source = '# NITERR=123\n' + source.replace('PRINT=0', 'PRINT=0\n\tNITERR=99')
    editor.editor.setPlainText(source)
    editor.show()
    editor.accept()
    assert editor.isVisible()
    assert editor.parameters is None
    assert editor.editor.toPlainText() == source
    assert source.splitlines()[editor.error_line - 1] == '\tNITERR=135'
    assert len(editor.editor.extraSelections()) == 1
    assert parameters.SCF.NITER() == 200
    editor.editor.setPlainText(source.replace('\n\tNITERR=135', ''))
    editor.accept()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert editor.parameters is not None


def test_guided_apply_failure_does_not_close_text_editor_or_add_history(application, monkeypatch):
    dialog = GuidedInputParametersDialog('scf', InputParameters.create('scf'))
    original_replace = dialog.session.replace_parameters

    def replace(parameters, **kwargs):
        if 'NITERR' in parameters.SCF:
            raise ValueError("Unknown option SCF.NITERR")
        return original_replace(parameters, **kwargs)

    def edit(editor):
        source = editor.editor.toPlainText().replace('NITER=200', 'NITER=200\n\tNITERR=135')
        editor.editor.setPlainText(source)
        editor.show()
        editor.accept()
        assert editor.isVisible()
        assert editor.error_line is not None
        assert dialog.session.undo_stack.count() == 0
        assert not dialog.session.is_modified()
        editor.reject()
        return editor.result()

    monkeypatch.setattr(dialog.session, 'replace_parameters', replace)
    monkeypatch.setattr(InputFileEditor, 'exec', edit)
    dialog.edit_input_button.click()
    assert not dialog.session.is_modified()
    dialog.close()
