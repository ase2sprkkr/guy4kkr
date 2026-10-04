"""Tests for the result-summary widget's input contract."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase2sprkkr.outputs.task_result import TaskResult
from PyQt6.QtWidgets import QApplication, QToolButton

from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Result(TaskResult):
    def __init__(self, output_values):
        self._output_values = output_values

    @property
    def output_values(self):
        if isinstance(self._output_values, Exception):
            raise self._output_values
        return self._output_values


class _BrokenItems:
    @staticmethod
    def items():
        raise RuntimeError("broken iteration")


class _Value:
    name = "value"
    display_name = "Display value"
    info = "Value information"

    def __init__(self, *, broken_label=False, broken_actions=False):
        self._broken_label = broken_label
        self._broken_actions = broken_actions

    def value_label(self):
        if self._broken_label:
            raise RuntimeError("broken label")
        return "Readable value"

    def actions(self):
        if self._broken_actions:
            raise RuntimeError("broken actions")
        return ()


def _widget(*, show_values_without_actions=True):
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=show_values_without_actions,
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


@pytest.mark.parametrize(
    "result,error",
    (
        (_Result(RuntimeError("broken values")), "broken values"),
        (_Result(_BrokenItems()), "broken iteration"),
    ),
)
def test_result_collection_failure_becomes_one_error_row(result, error, caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget()

    widget.set_result(result)

    assert widget._row_count == 1
    name = widget._grid.itemAtPosition(0, 0).widget()
    assert name.text() == "Output values could not be loaded ⚠"
    assert error in name.toolTip()
    assert "Failed to load result output values" in caplog.text
    widget.close()


def test_broken_output_value_does_not_hide_other_rows(caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    result = _Result({
        "good": _Value(),
        "bad": _Value(broken_label=True),
    })

    widget.set_result(result)

    assert widget._row_count == 2
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Display value"
    error_name = widget._grid.itemAtPosition(1, 0).widget()
    assert error_name.text() == "bad: unavailable ⚠"
    assert "broken label" in error_name.toolTip()
    assert "Failed to display output value 'bad'" in caplog.text
    widget.close()


def test_broken_actions_keep_value_visible_without_buttons(caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)

    widget.set_result(_Result({"bad": _Value(broken_actions=True)}))

    assert widget._row_count == 1
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Display value"
    buttons = widget._grid.itemAtPosition(0, 1).widget()
    assert not buttons.findChildren(QToolButton)
    summary = widget._grid.itemAtPosition(0, 2).widget()
    assert "Readable value" in summary.toolTip()
    assert "broken actions" in summary.toolTip()
    assert "Failed to load actions for output value 'bad'" in caplog.text
    widget.close()
