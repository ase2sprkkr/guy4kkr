import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase.build import bulk as build_bulk
from ase2sprkkr.sprkkr.build import semiinfinite_system
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.dialogs import workflow_window as workflow_module
from guy4ase.main import GuiApplication


def _workflow(tmp_path, *, workspace=None):
    gui = GuiApplication(
        workspace=workspace,
        recent_files_path=tmp_path / 'recent.json',
    )
    return gui, gui.create_workflow_window()


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


def test_load_output_is_only_available_on_the_start_screen(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)

    assert "Load SPR-KKR Output" in _action_titles(window)

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()

    assert "Load SPR-KKR Output" not in _action_titles(window)
    window.close()


def test_workflow_and_expert_share_one_workspace(tmp_path):
    application = QApplication.instance() or QApplication([])
    workspace = WorkspaceState()
    gui, window = _workflow(tmp_path, workspace=workspace)

    assert gui._main_window is None
    window._open_expert_mode()
    expert = gui.create_main_window()
    assert expert.workspace is workspace
    assert expert.controller is window.controller is gui.controller
    assert expert.recent_history is window.recent_history is gui.recent_files
    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert workspace.atoms is not None
    expert.close()
    window.close()


def test_structure_kind_follows_external_workspace_changes(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui, workflow = _workflow(tmp_path)
    expert = gui.create_main_window()
    bulk = Atoms('Fe', cell=(2.8, 2.8, 2.8), pbc=True)
    layer = semiinfinite_system(build_bulk("Fe", "bcc", a=2.8), (0, 0))

    expert.controller.replace_structure(bulk)
    application.processEvents()
    assert 'Create a 2D Surface' in _action_titles(workflow)
    assert _action_widget(
        workflow, workflow._GROUP_CALCULATE, 'Converge SCF'
    ).accessibleDescription() == 'Prepare and run a self-consistent calculation'

    expert.controller.replace_structure(layer)
    application.processEvents()
    assert 'Create a 2D Surface' not in _action_titles(workflow)
    assert _action_widget(
        workflow, workflow._GROUP_CALCULATE, 'Converge SCF'
    ).accessibleDescription() == (
        'Converge bulk region(s), then the interaction zone'
    )

    expert.controller.replace_structure(bulk)
    application.processEvents()
    assert 'Create a 2D Surface' in _action_titles(workflow)

    expert.controller.replace_structure(None)
    application.processEvents()
    assert 'Create a 3D Structure' in _action_titles(workflow)

    expert.close()
    workflow.close()


def test_start_actions_are_grouped_with_section_labels(tmp_path):
    _application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)

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
    assert all(label.font().bold() for label in labels)
    assert all(not label.styleSheet() for label in labels)
    create_button = _action_widget(
        window, "Create structure", "Create a 3D Structure"
    )
    load_button = _action_widget(
        window, "Load structure", "Load a Structure"
    )
    assert "#3979b8" in create_button.styleSheet()
    assert "#527f9f" in load_button.styleSheet()
    window.close()


def test_group_labels_follow_dark_and_light_palette_text_color(tmp_path):
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
            _gui, window = _workflow(tmp_path)
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


def test_structure_actions_follow_requested_group_order(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    window.controller.replace_structure(
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


def test_cancelled_surface_creation_does_not_reuse_previous_structure(
    tmp_path, monkeypatch
):
    workspace = WorkspaceState(
        atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    _gui, window = _workflow(tmp_path, workspace=workspace)
    builds = []
    monkeypatch.setattr(
        workflow_module.structure_flows,
        "create_structure",
        lambda _controller, _parent: None,
    )
    monkeypatch.setattr(
        workflow_module.structure_flows,
        "build_2d_structure",
        lambda *args, **kwargs: builds.append((args, kwargs)),
    )

    window._create_surface()

    assert builds == []
    assert workspace.atoms is not None
    window.close()
