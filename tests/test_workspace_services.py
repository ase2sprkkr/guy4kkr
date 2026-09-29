"""Document controller and recent-history service regressions."""
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


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
