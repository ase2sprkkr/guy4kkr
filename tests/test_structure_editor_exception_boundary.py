import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from guy4ase.gui.flows.structure_candidates import edit_structure_candidate


def test_structure_editor_programming_error_propagates():
    def broken_editor(_atoms, *, parent):
        raise RuntimeError("editor bug")

    with pytest.raises(RuntimeError, match="editor bug"):
        edit_structure_candidate(
            object(),
            broken_editor,
            None,
            error_title="Edit Error",
        )
