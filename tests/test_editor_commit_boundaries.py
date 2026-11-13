import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.widgets.input_parameters.commit import (
    EditorCommit,
    EditorValidationError,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_editor_commit_reports_explicit_validation_error(application):
    widget = QWidget()
    value = {"current": "old"}

    def read_value():
        return value["current"]

    def apply_value(_draft):
        raise EditorValidationError("invalid user value")

    commit = EditorCommit(widget, read_value, apply_value)
    value["current"] = "draft"

    assert not commit.commit()
    assert commit.error == "invalid user value"
    assert widget.toolTip() == "invalid user value"


def test_editor_commit_does_not_hide_apply_programming_error(application):
    widget = QWidget()
    value = {"current": "old"}

    def read_value():
        return value["current"]

    def apply_value(_draft):
        raise RuntimeError("session invariant")

    commit = EditorCommit(widget, read_value, apply_value)
    value["current"] = "draft"

    with pytest.raises(RuntimeError, match="session invariant"):
        commit.commit()

    assert commit.error == ""
    assert widget.toolTip() == ""
