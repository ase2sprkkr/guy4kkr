from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationNotReady,
    WorkspaceController,
)
from guy4ase.gui.dialogs import run_calculation as run_dialog
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import input_editing as input_editing_flow
from guy4ase.gui.flows import structures as structure_flows


class _Parameters:
    def __init__(self, name: str) -> None:
        self.name = name

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(f"{self.name}-copy")


def test_workspace_can_calculate_requires_all_inputs():
    workspace = WorkspaceState()
    assert not workspace.can_calculate()

    workspace.atoms = Atoms("Fe")
    assert not workspace.can_calculate()

    workspace.input_parameters = _Parameters("scf")
    assert not workspace.can_calculate()

    workspace.directory = "calculation"
    assert workspace.can_calculate()


def test_create_calculation_request_reports_missing_preconditions():
    controller = WorkspaceController(WorkspaceState())

    with pytest.raises(CalculationNotReady):
        controller.create_calculation_request()


def test_run_calculation_does_not_hide_parameter_copy_value_error(tmp_path):
    class BrokenParameters:
        def copy(self, *, copy_values: bool):
            assert copy_values
            raise ValueError("broken parameter copy")

    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=BrokenParameters(),
            directory=str(tmp_path),
        )
    )

    with pytest.raises(ValueError, match="broken parameter copy"):
        calculation_flow.run_calculation(
            controller,
            RecentFiles(),
            ActiveRunRegistry(),
            None,
        )


def test_run_calculation_does_not_hide_result_adoption_errors(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters("scf"),
            directory=str(tmp_path),
        )
    )
    monkeypatch.setattr(
        calculation_flow.SprkkrRunWindow,
        "_start",
        lambda _window, _request: None,
    )

    def broken_adoption(_loaded, *, expected_major):
        assert expected_major == controller.generation.major
        raise RuntimeError("broken adoption invariant")

    monkeypatch.setattr(
        controller,
        "adopt_calculation_result",
        broken_adoption,
    )

    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(),
        ActiveRunRegistry(),
        None,
    )
    assert window is not None

    with pytest.raises(RuntimeError, match="broken adoption invariant"):
        window._finished_callback(object())

    window.close()


def test_run_result_handoff_loads_once_and_preserves_backend_result(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    backend_result = object()
    output_path = tmp_path / "Fe.out"
    loaded = LoadedResult(
        result=backend_result,
        output_path=output_path,
        potential_path=None,
        atoms=None,
        potential_error=None,
        directory=str(tmp_path),
    )
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters("scf"),
            directory=str(tmp_path),
        )
    )
    history = RecentFiles(tmp_path / "recent.json")
    active_runs = ActiveRunRegistry()

    def capture_start(window, request):
        window._test_request = request

    monkeypatch.setattr(
        calculation_flow.SprkkrRunWindow,
        "_start",
        capture_start,
    )

    load_calls = []

    def fake_load_result(result, *, fallback_directory):
        load_calls.append((result, fallback_directory))
        assert result is backend_result
        return loaded

    monkeypatch.setattr(run_dialog, "load_result", fake_load_result)

    class Runner:
        def wait(self):
            return backend_result

    window = calculation_flow.run_calculation(
        controller,
        history,
        active_runs,
        None,
    )
    assert window is not None

    worker = run_dialog._SprkkrRunWorker(window._test_request)
    monkeypatch.setattr(worker, "_launch", lambda _calculator: Runner())
    worker.finished.connect(window._on_finished)
    worker.run()

    assert load_calls == [(backend_result, str(tmp_path))]
    assert controller.workspace.result is backend_result
    assert len(controller.workspace.result_history) == 1
    record = controller.workspace.result_history[0]
    assert record.result is backend_result
    assert record.current
    assert history.paths("output") == (str(output_path.resolve()),)

    window.close()


def test_edit_current_structure_reads_published_structure_and_commits_replacement():
    original = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=original))

    def edit(atoms, *, parent):
        assert parent is None
        assert atoms is original
        edited = atoms.copy()
        edited.symbols = "Cu"
        return edited

    assert structure_flows.edit_current_structure(
        controller,
        None,
        edit,
        error_title="Edit Error",
    )
    assert controller.workspace.atoms is not original
    assert original.get_chemical_symbols() == ["Fe"]
    assert controller.workspace.atoms.get_chemical_symbols() == ["Cu"]
    assert controller.workspace.restarted


def test_edit_current_input_parameters_commits_accepted_copy(monkeypatch):
    original_atoms = Atoms("Fe")
    original_parameters = _Parameters("original")
    edited_parameters = _Parameters("edited")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=original_atoms,
            input_parameters=original_parameters,
        )
    )

    def edit(parameters, *, parent, show_changed_only, atoms):
        assert parent is None
        assert not show_changed_only
        assert parameters is not original_parameters
        assert parameters.name == "original-copy"
        assert atoms is original_atoms
        return edited_parameters

    monkeypatch.setattr(
        input_editing_flow,
        "edit_input_parameters",
        edit,
    )

    assert input_editing_flow.edit_current_input_parameters(
        controller,
        None,
    )
    assert controller.workspace.input_parameters is edited_parameters


def test_choose_working_directory_is_shared_flow(monkeypatch, tmp_path):
    controller = WorkspaceController(WorkspaceState())
    chosen = tmp_path / "calculation"
    monkeypatch.setattr(
        calculation_flow.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(chosen),
    )

    assert calculation_flow.choose_working_directory(
        controller,
        None,
    )
    assert controller.workspace.directory == str(chosen)


def test_edit_site_elements_rejects_missing_structure_before_draft(monkeypatch):
    controller = WorkspaceController(WorkspaceState())
    messages = []

    def fail_if_called(_atoms):
        raise AssertionError("ElementAssignmentDraft must not receive None")

    monkeypatch.setattr(structure_flows, "ElementAssignmentDraft", fail_if_called)
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )

    assert not structure_flows.edit_site_elements(controller, None)
    assert messages == [
        ("No Structure", "Load or create a structure first."),
    ]
