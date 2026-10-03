"""Behavioral regressions for shared mutable structure access."""
from __future__ import annotations

from functools import partial
from threading import Event, Thread
from types import SimpleNamespace

from ase import Atoms
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application import workspace_controller as controller_module
from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    Busy,
    CalculationRequest,
    DocumentChange,
    WorkspaceController,
)
from guy4ase.gui.dialogs import run_calculation as run_dialog
from guy4ase.gui.misc.qt_structure_access import QtStructureAccess
from guy4ase.gui.misc.structure_wait import wait_for_structure


class _Parameters:
    def __init__(self, value: int):
        self.value = value
        self.copy_calls: list[bool] = []

    def copy(self, *, copy_values: bool):
        self.copy_calls.append(copy_values)
        return _Parameters(self.value)


def _hold_gate(controller, reason="preparing a calculation"):
    entered = Event()
    release = Event()

    def hold() -> None:
        def wait() -> None:
            entered.set()
            assert release.wait(5)

        controller.structure_gate.call(reason, wait)

    thread = Thread(target=hold)
    thread.start()
    assert entered.wait(5)
    return release, thread


def test_confirmed_structure_edit_emits_after_gate_release():
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot", result=object())
    )
    structures = []
    results = []
    signal_saw_unlocked = []

    def structure_changed(value):
        structures.append(value)
        probe = controller.structure_gate.try_call(
            "checking a signal", lambda: None
        )
        signal_saw_unlocked.append(not isinstance(probe, Busy))

    controller.structureChanged.connect(structure_changed)
    controller.resultChanged.connect(results.append)
    generation = controller.generation

    returned = controller.apply_structure_edit(
        lambda current: current,
        expected_generation=generation,
    )

    assert returned is DocumentChange.APPLIED
    assert controller.workspace.atoms is atoms
    assert controller.workspace.result is None
    assert controller.workspace.potential_path is None
    assert controller.generation == generation + 1
    assert structures == [atoms]
    assert results == [None]
    assert signal_saw_unlocked == [True]


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
    assert not isinstance(request, Busy)
    parameters.value = 11

    assert request.atoms is atoms
    assert request.input_parameters is not parameters
    assert request.input_parameters.value == 7
    assert parameters.copy_calls == [True]
    assert request.generation == controller.generation


def test_preparation_locks_only_structure_and_process_run_does_not(
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
    assert not isinstance(request, Busy)

    class Process:
        def run(self):
            assert not controller.structure_gate.locked()
            process_entered.set()
            assert release_process.wait(5)
            return object()

    class Calculator:
        def calculate(self, **kwargs):
            assert controller.structure_gate.locked()
            assert kwargs["atoms"] is atoms
            assert kwargs["input_parameters"] is request.input_parameters
            preparation_entered.set()
            assert release_preparation.wait(5)
            return Process()

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request, controller.structure_gate)
    thread = Thread(target=worker.run)
    thread.start()
    assert preparation_entered.wait(5)

    blocked = controller.replace_structure(Atoms("Cu"))
    assert isinstance(blocked, Busy)
    assert blocked.active_reason == "preparing a calculation"

    controller.change_working_directory(str(tmp_path / "other"))
    replacement_parameters = _Parameters(2)
    assert (
        controller.replace_input_parameters(replacement_parameters)
        is DocumentChange.APPLIED
    )
    assert controller.workspace.directory == str(tmp_path / "other")
    assert controller.workspace.input_parameters is replacement_parameters

    release_preparation.set()
    assert process_entered.wait(5)
    replacement = Atoms("Ni")
    assert controller.replace_structure(replacement) is DocumentChange.APPLIED
    assert controller.workspace.atoms is replacement

    release_process.set()
    thread.join(5)
    assert not thread.is_alive()


def test_preparation_exception_releases_gate_and_ends_activity(
    monkeypatch, tmp_path
):
    controller = WorkspaceController()
    registry = ActiveRunRegistry()
    request = CalculationRequest(Atoms("Fe"), _Parameters(1), str(tmp_path), 0)

    class Calculator:
        def calculate(self, **_kwargs):
            assert controller.structure_gate.locked()
            raise RuntimeError("preparation failed")

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request, controller.structure_gate)
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
    assert not controller.structure_gate.locked()
    assert not isinstance(
        controller.structure_gate.try_call("checking the gate", lambda: None),
        Busy,
    )


def test_unstarted_worker_reserves_neither_gate_nor_activity(tmp_path):
    controller = WorkspaceController()
    registry = ActiveRunRegistry()
    request = CalculationRequest(Atoms("Fe"), _Parameters(1), str(tmp_path), 0)
    worker = run_dialog._SprkkrRunWorker(request, controller.structure_gate)
    worker.activityStarted.connect(registry.register)
    worker.activityEnded.connect(registry.unregister)

    assert registry.count == 0
    assert not controller.structure_gate.locked()


def test_stale_result_and_element_draft_do_not_replace_new_document(tmp_path):
    original = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(
        WorkspaceState(atoms=original, directory=str(tmp_path))
    )
    draft_attempt = controller.read_structure(ElementAssignmentDraft)
    assert not isinstance(draft_attempt, Busy)
    source_generation, draft = draft_attempt
    request_generation = controller.generation
    replacement = Atoms("Cu")
    controller.replace_structure(replacement)

    result = SimpleNamespace(files={}, directory=str(tmp_path))
    adoption = controller.adopt_calculation_result(
        result, expected_generation=request_generation
    )
    assert not isinstance(adoption, Busy)
    assert not adoption.adopted
    assert controller.workspace.atoms is replacement
    assert controller.workspace.result is None

    change = controller.apply_structure_edit(
        lambda _atoms: draft.apply(),
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

    assert controller.generation == before_reset + 1


def test_busy_result_reports_the_current_structure_operation():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    caught = controller.reset()
    release.set()
    thread.join(5)

    assert isinstance(caught, Busy)
    assert caught.active_reason == "preparing a calculation"
    assert caught.requested_reason == "clearing the structure"


def test_modal_wait_cancel_does_not_interrupt_gate_owner():
    application = QApplication.instance() or QApplication([])
    parent = QWidget()
    atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    release, thread = _hold_gate(controller)
    labels = []

    def cancel_dialog() -> None:
        for widget in application.topLevelWidgets():
            if isinstance(widget, QProgressDialog):
                labels.append(widget.labelText())
                widget.cancel()

    QTimer.singleShot(0, cancel_dialog)
    outcome = wait_for_structure(parent, controller.reset)

    assert isinstance(outcome, Busy)
    assert controller.structure_gate.locked()
    assert controller.structure_gate.active_reason == "preparing a calculation"
    assert controller.workspace.atoms is atoms
    assert labels == [
        (
            "The structure is currently busy.\n"
            "Current operation: preparing a calculation.\n"
            "Waiting operation: clearing the structure."
        )
    ]
    release.set()
    thread.join(5)
    parent.close()


def test_modal_wait_retries_until_structure_operation_completes():
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    QTimer.singleShot(0, release.set)

    assert wait_for_structure(parent, controller.reset) is None
    thread.join(5)
    assert controller.workspace.atoms is None
    parent.close()


def test_structure_file_is_parsed_once_while_commit_retries(
    monkeypatch, tmp_path
):
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    atoms = Atoms("Fe")
    reads = []
    monkeypatch.setattr(
        controller_module,
        "ase_read",
        lambda path: reads.append(path) or atoms,
    )
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    prepared = controller.prepare_structure_load(tmp_path / "Fe.cif")
    release, thread = _hold_gate(controller)
    QTimer.singleShot(75, release.set)

    adopted = wait_for_structure(
        parent,
        partial(controller.adopt_loaded_structure, prepared),
    )
    thread.join(5)

    assert adopted is atoms
    assert reads == [(tmp_path / "Fe.cif").resolve()]
    parent.close()


def test_result_files_are_parsed_once_while_commit_retries(
    monkeypatch, tmp_path
):
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    potential.touch()
    result = SimpleNamespace(
        files={"output": output.name, "converged": potential.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    result_reads = []
    potential_reads = []
    result_atoms = Atoms("Fe")
    monkeypatch.setattr(
        controller_module.TaskResult,
        "from_file",
        staticmethod(lambda path: result_reads.append(path) or result),
    )
    monkeypatch.setattr(
        controller_module.Potential,
        "from_file",
        staticmethod(
            lambda path: potential_reads.append(path)
            or SimpleNamespace(atoms=result_atoms)
        ),
    )
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    prepared = controller.prepare_result_load(output)
    release, thread = _hold_gate(controller)
    QTimer.singleShot(75, release.set)

    adoption = wait_for_structure(
        parent,
        partial(controller.adopt_loaded_result, prepared),
    )
    thread.join(5)

    assert adoption.output_path == output.resolve()
    assert result_reads == [output.resolve()]
    assert potential_reads == [str(potential.resolve())]
    assert controller.workspace.atoms is result_atoms
    parent.close()


def test_background_structure_refresh_is_owned_and_eventually_runs():
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    loop = QEventLoop()
    completed = []

    access = QtStructureAccess(controller.structure_gate, parent)
    job = access.retry(
        lambda: controller.workspace.atoms,
        reason="refreshing the structure view",
        on_completed=lambda value: (completed.append(value), loop.quit()),
    )
    assert access.parent() is parent
    assert job.parent() is access
    assert completed == []

    QTimer.singleShot(0, release.set)
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    thread.join(5)

    assert completed == [controller.workspace.atoms]
    parent.close()
