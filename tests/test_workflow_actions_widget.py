from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.presentation import RecentLaunch
from guy4ase.gui.widgets.workflow_actions import WorkflowActionsWidget
from guy4ase.gui.workflow.model import (
    ActionIcon,
    AvailableAction,
    AvailableActionGroup,
    ContinueRecent,
    StartOver,
    WorkflowPlan,
    WorkflowSection,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_renderer_preserves_plan_group_order_and_presentation(tmp_path):
    _app()
    widget = WorkflowActionsWidget(RecentFiles(tmp_path / "recent.json"))
    first = AvailableAction(
        StartOver(),
        "First action",
        "First description",
        "neutral",
        ActionIcon.RESET,
    )
    second = AvailableAction(
        StartOver(),
        "Second action",
        "Second description",
        "destructive",
        ActionIcon.RESET,
    )
    plan = WorkflowPlan(
        "subtitle",
        (
            AvailableActionGroup(WorkflowSection.VIEW, "First group", (first,)),
            AvailableActionGroup(WorkflowSection.OTHER, "Second group", (second,)),
        ),
    )

    widget.set_plan(plan)

    assert widget.plan is plan
    labels = widget.findChildren(QLabel, "workflowActionGroupLabel")
    assert [label.text() for label in labels] == ["First group", "Second group"]
    buttons = widget.findChildren(QPushButton)
    assert [button.accessibleName() for button in buttons] == [
        "First action",
        "Second action",
    ]
    assert [button.accessibleDescription() for button in buttons] == [
        "First description",
        "Second description",
    ]
    widget.close()


def test_renderer_emits_typed_command_instead_of_interpreting_title(tmp_path):
    _app()
    widget = WorkflowActionsWidget(RecentFiles(tmp_path / "recent.json"))
    command = StartOver()
    widget.set_plan(
        WorkflowPlan(
            "subtitle",
            (
                AvailableActionGroup(
                    WorkflowSection.OTHER,
                    "Whatever",
                    (
                        AvailableAction(
                            command,
                            "Arbitrary copy",
                            "Copy may change without changing semantics",
                            "destructive",
                            ActionIcon.RESET,
                        ),
                    ),
                ),
            ),
        )
    )
    emitted = []
    widget.commandRequested.connect(emitted.append)

    widget.findChild(QPushButton).click()

    assert emitted == [command]
    widget.close()


def test_continue_recent_uses_menu_button_and_emits_recent_command(tmp_path):
    _app()
    output = tmp_path / "SCF.out"
    output.write_text("output", encoding="utf-8")
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("output", output)
    launch = RecentLaunch("output", str(output.resolve()))
    command = ContinueRecent(launch)
    widget = WorkflowActionsWidget(history)
    widget.set_plan(
        WorkflowPlan(
            "subtitle",
            (
                AvailableActionGroup(
                    WorkflowSection.LOAD,
                    "Load",
                    (
                        AvailableAction(
                            command,
                            launch.title,
                            "",
                            "load",
                            ActionIcon.CONTINUE,
                        ),
                    ),
                ),
            ),
        )
    )
    emitted = []
    widget.commandRequested.connect(emitted.append)

    button = widget.findChild(QToolButton)
    assert button is not None
    assert button.toolTip() == str(output.resolve())
    assert button.menu() is not None
    assert [action.text() for action in button.menu().actions()] == [
        "Structures",
        "Outputs",
    ]
    button.click()

    assert emitted == [command]
    widget.close()
