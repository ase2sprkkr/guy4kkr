"""Regressions for synchronous Guided editor draft commits."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.widgets.input_parameters.dataset import DATASET_PATH


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_commit_pending_applies_unfinished_text_draft(application):
    parameters = InputParameters.create("dos")
    parameters.SITES.NL = [3, 4]
    dialog = GuidedInputParametersDialog("dos", parameters)
    editor = dialog.editors_for(("SITES", "NL"))[0]

    editor.control.setText("[3, 5]")
    np.testing.assert_array_equal(dialog.session.value(("SITES", "NL")), [3, 4])

    assert dialog._commit_pending()
    np.testing.assert_array_equal(dialog.session.value(("SITES", "NL")), [3, 5])
    dialog.close()


def test_commit_pending_does_not_materialize_implicit_defaults(application):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    option = dialog.session.option(("SCF", "MIX"))
    assert not option.is_set()

    assert dialog._commit_pending()

    assert not dialog.session.option(("SCF", "MIX")).is_set()
    assert not dialog.session.is_modified()
    dialog.close()


def test_commit_pending_applies_dataset_without_focus_change(application):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    dialog.dataset_editor.edit.setText("parallel_run")
    assert not dialog.session.option(DATASET_PATH).is_set()

    assert dialog._commit_pending()

    assert dialog.session.value(DATASET_PATH) == "parallel_run"
    dialog.close()
