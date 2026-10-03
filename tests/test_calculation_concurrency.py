"""Behavioral regressions for shared workspace calculation preparation."""
from __future__ import annotations

from threading import Event, Thread
from types import SimpleNamespace

from ase import Atoms
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    Busy,
    CalculationRequest,
    Completed,
    DocumentChange,
    WorkspaceController,
)
from guy4ase.gui.dialogs import run_calculation as run_dialog
from guy4ase.gui.misc.qt_workspace_access import QtWorkspaceAccess
from guy4ase.gui.misc.workspace_wait import (
    wait_for_workspace,
    wait_for_workspace_action,
)


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

        controller.access_gate.call(reason, wait)

    thread = Thread(target=hold)
    thread.start()
    assert entered.wait(5)
    return release, thread


def test_confirmed_in_place_edit_is_a_document_change():
    atoms = Atoms("Fe")
    old_result = object()
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot", result=old_result)
    )
    structures = []
    results = []
    signal_saw_unlocked = []

    def structure_changed(value):
        structures.append(value)
        probe = controller.access_gate.try_call("checking a signal", lambda: None)
        signal_saw_unlocked.append(isinstance(probe, Completed))

    controller.structureChanged.connect(structure_changed)
    controller.resultChanged.connect(results.append)

    generation = controller.generation
    returned = controller.apply_structure_edit(
        lambda current: current,
        expected_generation=generation,
    )

    assert returned == Completed(DocumentChange.APPLIED)
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

    request_attempt = controller.create_calculation_request()
    assert isinstance(request_attempt, Completed)
    request = request_attempt.value
    parameters.value = 11

    assert request.atoms is atoms
    assert request.input_parameters is not parameters
    assert request.input_parameters.value == 7
    assert parameters.copy_calls == [True]
    assert request.generation == controller.generation


def test_preparation_excludes_gui_but_process_run_does_not(monkeypatch, tmp_path):
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
    request_attempt = controller.create_calculation_request()
    assert isinstance(request_attempt, Completed)
    request = request_attempt.value

    class Process:
        def run(self):
            assert not controller.access_gate.locked()
            process_entered.set()
            assert release_process.wait(5)
            return object()

    class Calculator:
        def calculate(self, **kwargs):
            assert controller.access_gate.locked()
            assert kwargs["atoms"] is atoms
            assert kwargs["input_parameters"] is request.input_parameters
            preparation_entered.set()
            assert release_preparation.wait(5)
            return Process()

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request, controller.access_gate)
    thread = Thread(target=worker.run)
    thread.start()
    assert preparation_entered.wait(5)

    busy = controller.replace_structure(Atoms("Cu"))
    assert isinstance(busy, Busy)
    assert busy.active_reason == "preparing a calculation"

    release_preparation.set()
    assert process_entered.wait(5)
    replacement = Atoms("Ni")
    controller.replace_structure(replacement)
    assert controller.workspace.atoms is replacement

    release_process.set()
    thread.join(5)
    assert not thread.is_alive()


def test_preparation_exception_releases_lock_and_ends_activity(
    monkeypatch, tmp_path
):
    controller = WorkspaceController()
    request = CalculationRequest(Atoms("Fe"), _Parameters(1), str(tmp_path), 0)

    class Calculator:
        def calculate(self, **_kwargs):
            assert controller.access_gate.locked()
            raise RuntimeError("preparation failed")

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    worker = run_dialog._SprkkrRunWorker(request, controller.access_gate)
    errors = []
    activity = []
    worker.error.connect(errors.append)
    worker.activityStarted.connect(lambda run_id: activity.append(("start", run_id)))
    worker.activityEnded.connect(lambda run_id: activity.append(("end", run_id)))
    worker.activityStarted.connect(controller.register_active_run)
    worker.activityEnded.connect(controller.unregister_active_run)

    worker.run()

    assert errors == ["preparation failed"]
    assert [event for event, _run_id in activity] == ["start", "end"]
    assert activity[0][1] is activity[1][1]
    assert controller.active_run_count == 0
    assert not controller.access_gate.locked()
    assert isinstance(
        controller.access_gate.try_call("checking the lock", lambda: None),
        Completed,
    )


def test_unstarted_worker_reserves_neither_lock_nor_activity(tmp_path):
    controller = WorkspaceController()
    request = CalculationRequest(Atoms("Fe"), _Parameters(1), str(tmp_path), 0)
    worker = run_dialog._SprkkrRunWorker(request, controller.access_gate)
    worker.activityStarted.connect(controller.register_active_run)
    worker.activityEnded.connect(controller.unregister_active_run)

    assert controller.active_run_count == 0
    assert not controller.access_gate.locked()
    assert worker.run_id not in controller._active_runs


def test_stale_result_and_element_draft_do_not_replace_new_document(tmp_path):
    original = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(
        WorkspaceState(atoms=original, directory=str(tmp_path))
    )
    draft_attempt = controller.read_structure(
        lambda atoms: ElementAssignmentDraft(atoms)
    )
    assert isinstance(draft_attempt, Completed)
    source_generation, draft = draft_attempt.value
    request_generation = controller.generation
    replacement = Atoms("Cu")
    controller.replace_structure(replacement)

    result = SimpleNamespace(files={}, directory=str(tmp_path))
    adoption_attempt = controller.adopt_calculation_result(
        result, expected_generation=request_generation
    )
    assert isinstance(adoption_attempt, Completed)
    adoption = adoption_attempt.value
    assert not adoption.adopted
    assert controller.workspace.atoms is replacement
    assert controller.workspace.result is None

    change = controller.apply_structure_edit(
        lambda _atoms: draft.apply(),
        expected_generation=source_generation,
    )
    assert change == Completed(DocumentChange.STALE)
    assert controller.workspace.atoms is replacement


def test_active_registry_counts_concurrent_worker_lifetimes():
    controller = WorkspaceController()
    counts = []
    controller.activeRunsChanged.connect(counts.append)
    first = object()
    second = object()

    controller.register_active_run(first)
    controller.register_active_run(second)
    controller.unregister_active_run(first)

    assert controller.active_run_count == 1
    assert counts == [1, 2, 1]
    controller.unregister_active_run(second)
    assert controller.active_run_count == 0
    assert counts[-1] == 0


def test_reset_advances_instead_of_resetting_generation():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    controller.replace_structure(controller.workspace.atoms)
    before_reset = controller.generation

    controller.reset()

    assert controller.generation == before_reset + 1


def test_busy_result_reports_the_current_lock_reason():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    caught = controller.reset()
    release.set()
    thread.join(5)

    assert isinstance(caught, Busy)
    assert caught.active_reason == "preparing a calculation"
    assert caught.requested_reason == "clearing the workspace"


def test_modal_wait_can_be_canceled_without_interrupting_lock_owner():
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
    outcome = wait_for_workspace(parent, controller.reset)

    assert not outcome.completed
    assert controller.access_gate.locked()
    assert controller.access_gate.active_reason == "preparing a calculation"
    assert controller.workspace.atoms is atoms
    assert labels == [
        "The workspace is currently busy.\n"
        "Current operation: preparing a calculation.\n"
        "Waiting operation: clearing the workspace."
    ]
    release.set()
    thread.join(5)
    parent.close()


def test_modal_wait_retries_and_button_helper_returns_success():
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    QTimer.singleShot(0, release.set)

    assert wait_for_workspace_action(parent, controller.reset)
    thread.join(5)
    assert controller.workspace.atoms is None
    parent.close()


def test_background_retry_is_owned_and_repeats_until_completed():
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    release, thread = _hold_gate(controller)
    loop = QEventLoop()
    completed = []

    access = QtWorkspaceAccess(controller, parent)
    job = access.retry_call(
        controller.reset,
        on_completed=lambda value: (completed.append(value), loop.quit()),
    )
    assert access.parent() is parent
    assert job.parent() is access
    assert controller.workspace.atoms is not None

    QTimer.singleShot(0, release.set)
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    thread.join(5)

    assert completed == [None]
    assert controller.workspace.atoms is None
    parent.close()
