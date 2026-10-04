"""Tests for the result-summary widget's input contract."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase2sprkkr.outputs.task_result import TaskResult
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.widgets.result_actions import ResultActionsWidget


def _widget():
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )


def test_result_actions_render_task_result():
    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    result = TaskResult(
        None,
        None,
        None,
        output_file="result.out",
    )

    widget.set_result(result)

    assert widget.has_rows
    widget.close()
