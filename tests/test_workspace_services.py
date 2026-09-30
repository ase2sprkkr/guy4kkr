"""Document controller and recent-history service regressions."""
from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    ResultArtifacts,
    WorkspaceController,
)
from guy4ase.gui.flows.operations import GuiOperations


@pytest.fixture
def gui_operations(tmp_path):
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    return GuiOperations(controller, history)


def test_recent_files_roundtrip_is_bounded_and_repairs_missing_entries(tmp_path):
    existing = tmp_path / "Fe.cif"
    existing.touch()
    missing = tmp_path / "missing.out"
    history = RecentFiles(tmp_path / "recent.json", limit=2)

    history.remember("structure", existing)
    history.remember("structure", tmp_path / "older.cif")
    history.remember("structure", existing)
    history.remember("output", missing)

    loaded = RecentFiles(history.path, limit=2)
    loaded.load()
    assert loaded.paths("structure") == (
        str(existing),
        str(tmp_path / "older.cif"),
    )
    assert loaded.last_kind == "output"

    loaded.remove_missing()
    assert loaded.paths("structure") == (str(existing),)
    assert loaded.paths("output") == ()
    assert loaded.last_kind == "structure"


def test_workspace_controller_owns_mutations_and_change_notifications():
    workspace = WorkspaceState()
    controller = WorkspaceController(workspace)
    changes: list[tuple[str, object]] = []
    controller.structureChanged.connect(
        lambda value: changes.append(("structure", value))
    )
    controller.inputParametersChanged.connect(
        lambda value: changes.append(("input", value))
    )
    controller.directoryChanged.connect(
        lambda value: changes.append(("directory", value))
    )
    controller.resultChanged.connect(
        lambda value: changes.append(("result", value))
    )

    atoms = Atoms("Fe")
    parameters = object()
    result = object()
    controller.set_structure(atoms, potential_path="Fe.pot")
    controller.set_input_parameters(parameters)
    controller.set_directory("calculation")
    controller.adopt_result(result)

    assert workspace.atoms is atoms
    assert workspace.input_parameters is parameters
    assert workspace.directory == "calculation"
    assert workspace.potential_path == "Fe.pot"
    assert workspace.result is result
    assert changes == [
        ("structure", atoms),
        ("input", parameters),
        ("directory", "calculation"),
        ("result", result),
    ]

    controller.reset()
    assert workspace.atoms is None
    assert workspace.input_parameters is None
    assert workspace.directory is None
    assert workspace.potential_path is None
    assert workspace.result is None
    assert changes[-4:] == [
        ("structure", None),
        ("input", None),
        ("directory", None),
        ("result", None),
    ]


def test_restart_scf_is_a_document_operation():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        )
    )
    controller = WorkspaceController(WorkspaceState(atoms=atoms))

    controller.restart_scf()

    assert atoms.potential.SCF_INFO.SCFSTATUS == "START"


def test_adopt_result_resolves_artifacts_and_working_directory(tmp_path):
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    result = SimpleNamespace(
        files={"output": "Fe.out", "converged": "Fe.pot"},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    controller = WorkspaceController()

    artifacts = controller.adopt_result(result)

    assert artifacts.output_path == output
    assert artifacts.potential_path == potential
    assert controller.workspace.result is result
    assert controller.workspace.directory == str(tmp_path.resolve())


def test_gui_operations_applies_shared_result_side_effects(tmp_path, monkeypatch):
    selected_output = tmp_path / "selected.out"
    discovered_output = tmp_path / "reported.out"
    potential = tmp_path / "converged.pot"
    artifacts = ResultArtifacts(discovered_output, potential)
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    operations = GuiOperations(controller, history)
    result = object()
    adopted: list[tuple[object, object]] = []
    potential_loads: list[tuple[object, object, str]] = []
    parent = object()

    def adopt(value, *, fallback_directory=None):
        adopted.append((value, fallback_directory))
        return artifacts

    monkeypatch.setattr(controller, "adopt_result", adopt)
    monkeypatch.setattr(
        operations,
        "_load_result_potential",
        lambda path, owner, prefix: potential_loads.append(
            (path, owner, prefix)
        ),
    )

    returned = operations.adopt_result(
        result,
        parent,
        fallback_directory=tmp_path,
        recent_output=selected_output,
        potential_error_prefix="Potential warning",
    )

    assert returned is artifacts
    assert adopted == [(result, tmp_path)]
    assert history.paths("output") == (str(selected_output),)
    assert potential_loads == [(potential, parent, "Potential warning")]


def test_gui_operations_uses_discovered_output_without_explicit_recent_path(
    tmp_path, monkeypatch
):
    output = tmp_path / "finished.out"
    artifacts = ResultArtifacts(output, None)
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    operations = GuiOperations(controller, history)
    monkeypatch.setattr(
        controller,
        "adopt_result",
        lambda result, *, fallback_directory=None: artifacts,
    )
    monkeypatch.setattr(operations, "_load_result_potential", lambda *args: None)

    operations.adopt_result(object(), object())

    assert history.paths("output") == (str(output),)


def test_loading_unknown_structure_from_file_warns_but_keeps_it(
    tmp_path, monkeypatch, gui_operations
):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 8.0), pbc=(True, True, False))
    warnings = []
    monkeypatch.setattr(
        "guy4ase.gui.flows.operations.ase_read", lambda _path: atoms
    )
    monkeypatch.setattr(
        "guy4ase.gui.flows.operations.QMessageBox.warning",
        lambda parent, title, message: warnings.append((parent, title, message)),
    )
    path = tmp_path / "layer.xyz"

    assert gui_operations.load_structure(path, parent := object())

    assert gui_operations.workspace.atoms is atoms
    assert warnings == [
        (
            parent,
            "Unknown Structure Type",
            (
                "The loaded structure could not be recognized as a supported "
                "3D bulk or SPR-KKR 2D layered structure. Check its periodic "
                "boundary conditions and, for a 2D structure, its left, "
                "central, and right regions before calculating."
            ),
        )
    ]


@pytest.mark.parametrize(
    "method_name, selection_target",
    [
        (
            "create_structure_from_database",
            "guy4ase.gui.flows.operations.chain_dialogs",
        ),
        (
            "download_structure",
            "guy4ase.gui.flows.operations.select_online_structure",
        ),
    ],
)
def test_loading_unknown_structure_from_database_warns(
    monkeypatch, gui_operations, method_name, selection_target
):
    atoms = Atoms("Fe", pbc=False)
    warnings = []
    monkeypatch.setattr(selection_target, lambda *args, **kwargs: atoms)
    monkeypatch.setattr(
        "guy4ase.gui.flows.operations.QMessageBox.warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    result = getattr(gui_operations, method_name)(object())

    assert result is atoms
    assert gui_operations.workspace.atoms is atoms
    assert [title for title, _message in warnings] == [
        "Unknown Structure Type"
    ]


def test_loading_known_structure_does_not_warn(monkeypatch, gui_operations):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    warnings = []
    monkeypatch.setattr(
        "guy4ase.gui.flows.operations.select_online_structure",
        lambda **_kwargs: atoms,
    )
    monkeypatch.setattr(
        "guy4ase.gui.flows.operations.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )

    gui_operations.download_structure(object())

    assert warnings == []
