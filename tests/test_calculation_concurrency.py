"""Behavioral regressions for versioned read-only workspace structures."""
from __future__ import annotations

from threading import Event, Thread
from types import SimpleNamespace

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application import result_loading as result_loading_module
from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import (
    load_result,
    load_result_file,
)
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    DocumentChange,
    Generation,
    WorkspaceController,
)
from guy4ase.gui.dialogs import run_calculation as run_dialog
from guy4ase.gui.flows import files as file_flows


class _Parameters:
    def __init__(self, value: int):
        self.value = value
        self.copy_calls: list[bool] = []

    def copy(self, *, copy_values: bool):
        self.copy_calls.append(copy_values)
        return _Parameters(self.value)


def test_confirmed_structure_edit_is_copy_on_write():
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot", result=object())
    )
    structures = []
    results = []
    controller.structureChanged.connect(structures.append)
    controller.resultChanged.connect(results.append)
    generation = controller.generation

    def edit(candidate):
        assert candidate is not atoms
        candidate.symbols = "Cu"
        return candidate

    returned = controller.apply_structure_edit(
        edit,
        expected_generation=generation,
    )

    assert returned is DocumentChange.APPLIED
    assert controller.workspace.atoms is not atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert controller.workspace.atoms.get_chemical_symbols() == ["Cu"]
    assert controller.workspace.result is None
    assert controller.workspace.potential_path is None
    assert controller.generation == generation.next_major()
    assert structures == [controller.workspace.atoms]
    assert results == [None]


def test_failed_structure_edit_leaves_published_atoms_untouched():
    atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    generation = controller.generation

    def fail(candidate):
        candidate.symbols = "Cu"
        raise RuntimeError("edit failed")

    try:
        controller.apply_structure_edit(fail, expected_generation=generation)
    except RuntimeError as exc:
        assert str(exc) == "edit failed"
    else:  # pragma: no cover - assertion helper
        raise AssertionError("edit must propagate the callback error")

    assert controller.atoms is atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert controller.generation == generation


def test_run_request_borrows_atoms_and_owns_parameter_values(tmp_path):
    class UncopyableAtoms(Atoms):
        def copy(self):  # pragma: no cover - failure is the assertion
            raise AssertionError("calculation request must not copy Atoms")

    atoms = UncopyableAtoms("Fe")
    parameters = _Parameters(7)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )

    request = controller.create_calculation_request()
    parameters.value = 11

    assert request.atoms is atoms
    assert request.input_parameters is not parameters
    assert request.input_parameters.value == 7
    assert parameters.copy_calls == [True]
    assert request.generation == controller.generation


def test_calculation_preparation_does_not_block_new_workspace_version(
    monkeypatch, tmp_path
):
    preparation_entered = Event()
    release_preparation = Event()
    process_entered = Event()
    release_process = Event()
    atoms = Atoms("Fe")
    parameters = _Parameters(1)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )
    request = controller.create_calculation_request()

    class Process:
        def run(self):
            process_entered.set()
            assert release_process.wait(5)
            return object()

    class Calculator:
        def calculate(self, **kwargs):
            assert kwargs["atoms"] is atoms
            assert kwargs["input_parameters"] is request.input_parameters
            preparation_entered.set()
            assert release_preparation.wait(5)
            return Process()

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request)
    thread = Thread(target=worker.run)
    thread.start()
    assert preparation_entered.wait(5)

    replacement = Atoms("Ni")
    generation = controller.generation
    assert controller.replace_structure(replacement) is DocumentChange.APPLIED
    assert controller.atoms is replacement
    assert controller.generation == generation.next_major()

    release_preparation.set()
    assert process_entered.wait(5)
    release_process.set()
    thread.join(5)
    assert not thread.is_alive()


def test_preparation_exception_ends_activity(monkeypatch, tmp_path):
    registry = ActiveRunRegistry()
    request = CalculationRequest(
        Atoms("Fe"), _Parameters(1), str(tmp_path), Generation()
    )

    class Calculator:
        def calculate(self, **_kwargs):
            raise RuntimeError("preparation failed")

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request)
    errors = []
    activity = []
    worker.error.connect(errors.append)
    worker.activityStarted.connect(lambda run_id: activity.append(("start", run_id)))
    worker.activityEnded.connect(lambda run_id: activity.append(("end", run_id)))
    worker.activityStarted.connect(registry.register)
    worker.activityEnded.connect(registry.unregister)

    worker.run()

    assert errors == ["preparation failed"]
    assert [event for event, _run_id in activity] == ["start", "end"]
    assert activity[0][1] is activity[1][1]
    assert registry.count == 0


def test_unstarted_worker_reserves_no_activity(tmp_path):
    registry = ActiveRunRegistry()
    request = CalculationRequest(
        Atoms("Fe"), _Parameters(1), str(tmp_path), Generation()
    )
    worker = run_dialog._SprkkrRunWorker(request)
    worker.activityStarted.connect(registry.register)
    worker.activityEnded.connect(registry.unregister)

    assert registry.count == 0


def test_stale_result_and_element_draft_do_not_replace_new_document(tmp_path):
    original = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(
        WorkspaceState(atoms=original, directory=str(tmp_path))
    )
    source_generation = controller.generation
    draft = ElementAssignmentDraft(controller.atoms)
    request_generation = controller.generation
    replacement = Atoms("Cu")
    controller.replace_structure(replacement)

    result = SimpleNamespace(files={}, directory=str(tmp_path))
    loaded = load_result(result, fallback_directory=tmp_path)
    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=request_generation
    )
    assert not adoption.adopted
    assert controller.workspace.atoms is replacement
    assert controller.workspace.result is None

    change = controller.apply_structure_edit(
        lambda atoms: draft.apply(atoms),
        expected_generation=source_generation,
    )
    assert change is DocumentChange.STALE
    assert controller.workspace.atoms is replacement


def test_active_registry_counts_concurrent_worker_lifetimes():
    registry = ActiveRunRegistry()
    counts = []
    registry.countChanged.connect(counts.append)
    first = object()
    second = object()

    registry.register(first)
    registry.register(second)
    registry.unregister(first)

    assert registry.count == 1
    assert counts == [1, 2, 1]
    registry.unregister(second)
    assert registry.count == 0
    assert counts[-1] == 0


def test_reset_advances_instead_of_resetting_generation():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    controller.replace_structure(controller.workspace.atoms)
    before_reset = controller.generation

    controller.reset()

    assert controller.generation == before_reset.next_major()


def test_file_loads_reject_an_intervening_document_change(
    monkeypatch, tmp_path
):
    loaded_atoms = Atoms("Fe")
    result = SimpleNamespace(files={}, directory=str(tmp_path))
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )

    structure_controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Cu"))
    )
    original_structure = structure_controller.workspace.atoms
    structure_history = RecentFiles(tmp_path / "structure-recent.json")

    def read_structure(_path):
        structure_controller.replace_input_parameters(object())
        return loaded_atoms

    monkeypatch.setattr(file_flows, "ase_read", read_structure)
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )
    structure_loaded = file_flows.load_structure(
        structure_controller,
        structure_history,
        tmp_path / "Fe.cif",
        object(),
    )

    result_controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Cu"))
    )
    original_result_structure = result_controller.workspace.atoms
    result_generation = result_controller.generation

    loaded_result = load_result_file(tmp_path / "Fe.out")
    result_controller.replace_input_parameters(object())
    result_adoption = result_controller.adopt_external_result(
        loaded_result,
        expected_generation=result_generation,
    )

    assert not structure_loaded
    assert not result_adoption.adopted
    assert structure_controller.workspace.atoms is original_structure
    assert structure_history.paths("structure") == ()
    assert result_controller.workspace.atoms is original_result_structure
    assert result_controller.workspace.result is None


def test_directory_change_invalidates_and_rejects_stale_calculation_result(
    tmp_path,
):
    original_directory = tmp_path / "first"
    next_directory = tmp_path / "next"
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(original_directory))
    )
    generation = controller.generation
    result = SimpleNamespace(files={}, directory=str(original_directory))
    loaded = load_result(result, fallback_directory=original_directory)

    controller.change_directory(str(next_directory))

    assert controller.generation == generation.next_major()
    assert controller.workspace.result is None
    assert controller.workspace.directory == str(next_directory)

    adoption = controller.adopt_calculation_result(
        loaded,
        expected_generation=generation,
    )
    assert not adoption.adopted
    assert controller.generation == generation.next_major()
    assert controller.workspace.result is None
    assert controller.workspace.directory == str(next_directory)


def test_structure_file_is_parsed_before_revision_checked(monkeypatch, tmp_path):
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    reads = []
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    history = RecentFiles(tmp_path / "recent.json")

    def read(path):
        reads.append(path)
        controller.replace_input_parameters(object())
        return atoms

    monkeypatch.setattr(file_flows, "ase_read", read)
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert not file_flows.load_structure(
        controller, history, tmp_path / "Fe.cif", parent
    )
    assert reads == [(tmp_path / "Fe.cif").resolve()]
    assert history.paths("structure") == ()
    parent.close()
