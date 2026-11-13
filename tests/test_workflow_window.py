import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.dialogs import workflow_window as workflow_module
from guy4ase.gui.workflow.model import (
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
)
from guy4ase.main import GuiApplication


def _workflow(tmp_path, *, workspace=None):
    gui = GuiApplication(
        workspace=workspace,
        recent_files_path=tmp_path / "recent.json",
    )
    return gui, gui.create_workflow_window()


def _commands(window):
    return tuple(
        action.command
        for group in window.workflow_plan.groups
        for action in group.actions
    )


def test_workflow_and_expert_share_one_workspace(tmp_path):
    application = QApplication.instance() or QApplication([])
    workspace = WorkspaceState()
    gui, window = _workflow(tmp_path, workspace=workspace)

    assert gui._main_window is None
    window._open_expert_mode()
    expert = gui.create_main_window()
    assert expert.controller is window.controller is gui.controller
    assert expert.recent_history is window.recent_history is gui.recent_files

    expert.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()

    assert workspace.atoms is not None
    assert expert.controller.atoms is workspace.atoms
    assert RunTask("scf") in _commands(window)
    expert.close()
    window.close()


def test_workspace_signals_refresh_semantic_plan(tmp_path):
    application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)

    assert CreateStructure(CreateStructureKind.THREE_D) in _commands(window)

    window.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert RunTask("scf") in _commands(window)
    assert CreateStructure(CreateStructureKind.THREE_D) not in _commands(window)

    window.controller.reset()
    application.processEvents()
    assert CreateStructure(CreateStructureKind.THREE_D) in _commands(window)
    window.close()


def test_typed_commands_are_dispatched_without_title_interpretation(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    _gui, window = _workflow(tmp_path)
    events = []

    monkeypatch.setattr(
        window,
        "_prepare_task",
        lambda task: events.append(("task", task)),
    )
    monkeypatch.setattr(window, "_update_empty_spheres", lambda: events.append("spheres"))
    monkeypatch.setattr(window, "_create_3d", lambda: events.append("create-3d"))
    monkeypatch.setattr(
        window, "_create_from_database", lambda: events.append("prototype")
    )
    monkeypatch.setattr(window, "_create_surface", lambda: events.append("surface"))
    monkeypatch.setattr(
        window, "_create_transition", lambda: events.append("transition")
    )
    monkeypatch.setattr(
        window,
        "_build_2d",
        lambda _checked=False, *, surface_mode=False: events.append(
            ("build-2d", surface_mode)
        ),
    )
    monkeypatch.setattr(window, "_download_structure", lambda: events.append("download"))
    monkeypatch.setattr(window, "_load_structure", lambda: events.append("load-structure"))
    monkeypatch.setattr(window, "_load_output", lambda: events.append("load-output"))
    monkeypatch.setattr(
        window,
        "_continue_recent",
        lambda kind, path: events.append(("recent", kind, path)),
    )
    monkeypatch.setattr(window, "_visualize_structure", lambda: events.append("view"))
    monkeypatch.setattr(
        window, "_use_for_new_calculation", lambda: events.append("new-calculation")
    )
    monkeypatch.setattr(window, "_start_over", lambda: events.append("reset"))

    commands = (
        RunTask("scf"),
        UpdateEmptySpheres(),
        CreateStructure(CreateStructureKind.THREE_D),
        CreateStructure(CreateStructureKind.PROTOTYPE),
        CreateStructure(CreateStructureKind.SURFACE),
        CreateStructure(CreateStructureKind.TWO_D),
        Build2D(Build2DKind.SURFACE),
        Build2D(Build2DKind.STRUCTURE),
        Load(LoadKind.ONLINE_STRUCTURE),
        Load(LoadKind.STRUCTURE),
        Load(LoadKind.OUTPUT),
        ContinueRecent("output", "/tmp/result.out"),
        VisualizeStructure(),
        UseForNewCalculation(),
        StartOver(),
    )
    for command in commands:
        window.execute_workflow_command(command)

    assert events == [
        ("task", "scf"),
        "spheres",
        "create-3d",
        "prototype",
        "surface",
        "transition",
        ("build-2d", True),
        ("build-2d", False),
        "download",
        "load-structure",
        "load-output",
        ("recent", "output", "/tmp/result.out"),
        "view",
        "new-calculation",
        "reset",
    ]
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
