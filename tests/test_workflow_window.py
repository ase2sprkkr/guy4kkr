import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel

from guy4ase.gui.dialogs.workflow_window import WorkflowWindow


def _action_title(widget):
    return str(
        widget.property("workflowActionTitle")
        or widget.text().splitlines()[0]
    )


def _action_titles(window):
    titles = []
    for group in window._ACTION_GROUPS:
        layout = window._action_group_layouts.get(group)
        if layout is None:
            continue
        titles.extend(
            _action_title(layout.itemAt(index).widget())
            for index in range(1, layout.count())
        )
    return titles


def _group_titles(window):
    return [
        window._actions_layout.itemAt(index)
        .widget()
        .findChild(QLabel, "workflowActionGroupLabel")
        .text()
        for index in range(window._actions_layout.count())
    ]


def _actions_in_group(window, group):
    layout = window._action_group_layouts[group]
    return [
        _action_title(layout.itemAt(index).widget())
        for index in range(1, layout.count())
    ]


def _action_widget(window, group, title):
    layout = window._action_group_layouts[group]
    return next(
        layout.itemAt(index).widget()
        for index in range(1, layout.count())
        if _action_title(layout.itemAt(index).widget()) == title
    )


def test_load_output_is_only_available_on_the_start_screen():
    application = QApplication.instance() or QApplication([])
    window = WorkflowWindow()

    assert "Load SPR-KKR Output" in _action_titles(window)

    window.expert_window.set_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()

    assert "Load SPR-KKR Output" not in _action_titles(window)
    window.close()


def test_start_actions_are_grouped_with_small_labels():
    application = QApplication.instance() or QApplication([])
    window = WorkflowWindow()

    assert _group_titles(window) == [
        "Create structure",
        "Load structure",
    ]
    assert "Create a 3D Structure" in _actions_in_group(
        window, "Create structure"
    )
    assert "Download Structure from Online Database" in _actions_in_group(
        window, "Load structure"
    )
    assert "Load SPR-KKR Output" in _actions_in_group(
        window, "Load structure"
    )
    labels = window._actions.findChildren(
        QLabel, "workflowActionGroupLabel"
    )
    assert all("font-size: 9pt" in label.styleSheet() for label in labels)
    assert all("color:" not in label.styleSheet() for label in labels)
    create_button = _action_widget(
        window, "Create structure", "Create a 3D Structure"
    )
    load_button = _action_widget(
        window, "Load structure", "Load a Structure"
    )
    assert "#3979b8" in create_button.styleSheet()
    assert "#527f9f" in load_button.styleSheet()
    window.close()


def test_group_labels_follow_dark_and_light_palette_text_color():
    application = QApplication.instance() or QApplication([])
    original_palette = application.palette()
    try:
        for window_color, text_color in (
            (QColor("#202020"), QColor("#ffffff")),
            (QColor("#ffffff"), QColor("#202020")),
        ):
            palette = QPalette(original_palette)
            palette.setColor(QPalette.ColorRole.Window, window_color)
            palette.setColor(QPalette.ColorRole.WindowText, text_color)
            application.setPalette(palette)
            window = WorkflowWindow()
            labels = window._actions.findChildren(
                QLabel, "workflowActionGroupLabel"
            )

            assert labels
            assert all(
                label.palette().color(QPalette.ColorRole.WindowText)
                == text_color
                for label in labels
            )
            window.close()
    finally:
        application.setPalette(original_palette)


def test_structure_actions_follow_requested_group_order():
    application = QApplication.instance() or QApplication([])
    window = WorkflowWindow()
    window.expert_window.set_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    window._scf_status = lambda _atoms: "CONVERGED"
    window._refresh()
    application.processEvents()

    assert _group_titles(window) == [
        "Calculate",
        "Create derived structure",
        "And now something completely different...",
    ]
    assert "Calculate DOS" in _actions_in_group(window, "Calculate")
    assert "Create a 2D Surface" in _actions_in_group(
        window, "Create structure"
    )
    assert _actions_in_group(
        window, window._GROUP_DIFFERENT
    ) == ["Recalculate SCF", "Start Over"]
    recalculate = _action_widget(
        window,
        window._GROUP_DIFFERENT,
        "Recalculate SCF",
    )
    start_over = _action_widget(
        window,
        window._GROUP_DIFFERENT,
        "Start Over",
    )
    assert "#b34444" in recalculate.styleSheet()
    assert "#b34444" in start_over.styleSheet()
    window.close()
