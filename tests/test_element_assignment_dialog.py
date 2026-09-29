"""Thin Qt integration tests for element assignment."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import numpy as np
from ase import Atoms
from PyQt6.QtWidgets import QApplication, QDialog

from guy4ase.gui.dialogs.structures.element_assignment import (
    ElementAssignmentDialog,
)


def _atoms() -> Atoms:
    atoms = Atoms(
        "Fe2",
        scaled_positions=((0, 0, 0), (0.5, 0.5, 0.5)),
        cell=np.eye(3),
        pbc=True,
    )
    atoms.set_array("spacegroup_kinds", np.asarray((0, 0), dtype=int))
    atoms.set_array("labels", np.asarray(("a.1", "a.2"), dtype=object))
    atoms.info["occupancy"] = {"0": {"Fe": 1.0}}
    return atoms


def test_break_button_delegates_to_model_and_refreshes_rows():
    application = QApplication.instance() or QApplication([])
    dialog = ElementAssignmentDialog()
    dialog.setup(_atoms())
    original_site = dialog._draft.sites[0]
    calls = []
    original_split = dialog._draft.split_site

    def split(site):
        calls.append(site)
        return original_split(site)

    dialog._draft.split_site = split
    dialog._letter_widgets[0].break_btn.click()
    application.processEvents()

    assert calls == [original_site]
    assert len(dialog._draft.sites) == 2
    assert [row.label for row in dialog._letter_widgets] == ["a.1", "a.2"]
    dialog.close()


def test_cancel_does_not_apply_working_state_to_source():
    application = QApplication.instance() or QApplication([])
    atoms = _atoms()
    original = atoms.copy()
    dialog = ElementAssignmentDialog()
    dialog.setup(atoms)

    dialog._letter_widgets[0].break_btn.click()
    dialog.reject()
    application.processEvents()

    np.testing.assert_array_equal(atoms.positions, original.positions)
    np.testing.assert_array_equal(
        atoms.get_array("spacegroup_kinds"),
        original.get_array("spacegroup_kinds"),
    )
    dialog.close()


def test_accept_builds_result_from_model():
    application = QApplication.instance() or QApplication([])
    dialog = ElementAssignmentDialog()
    dialog.setup(_atoms())
    dialog._letter_widgets[0].break_btn.click()

    dialog._on_ok()
    application.processEvents()

    assert dialog.result() == QDialog.DialogCode.Accepted
    np.testing.assert_array_equal(
        dialog._result.get_array("spacegroup_kinds"), (0, 1)
    )
    dialog.close()
