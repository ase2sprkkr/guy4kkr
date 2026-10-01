"""Document state, file-flow and shared-lifetime regressions."""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import textwrap
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest
from ase import Atoms
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application import workspace_controller as controller_module
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    ResultAdoption,
    WorkspaceController,
)
from guy4ase.gui.dialogs import object_view
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows


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


def test_recent_files_emits_only_for_real_changes(tmp_path):
    existing = tmp_path / "Fe.cif"
    existing.touch()
    history = RecentFiles(tmp_path / "recent.json")
    changes = []
    history.changed.connect(lambda: changes.append(history.snapshot))

    history.remember("structure", existing)
    history.remember("structure", existing)
    history.forget("structure", tmp_path / "absent.cif")
    assert len(changes) == 1

    history.forget("structure", existing)
    assert len(changes) == 2

    history.remember("structure", existing)
    existing.unlink()
    history.remove_missing()
    assert len(changes) == 4


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
    controller.change_working_directory("calculation")
    controller.replace_structure(atoms, potential_path="Fe.pot")
    controller.replace_input_parameters(parameters)
    controller.adopt_calculation_result(result)

    assert workspace.atoms is atoms
    assert workspace.input_parameters is parameters
    assert workspace.directory == "calculation"
    assert workspace.potential_path == "Fe.pot"
    assert workspace.result is result
    assert changes == [
        ("directory", "calculation"),
        ("structure", atoms),
        ("input", parameters),
        ("result", result),
    ]

    controller.reset()
    assert workspace == WorkspaceState()
    assert changes[-4:] == [
        ("result", None),
        ("structure", None),
        ("input", None),
        ("directory", None),
    ]


def test_replacing_structure_invalidates_result_and_potential_source():
    old_atoms = Atoms("Fe")
    new_atoms = Atoms("Cu")
    parameters = object()
    workspace = WorkspaceState(
        atoms=old_atoms,
        input_parameters=parameters,
        directory="calculation",
        potential_path="Fe.pot",
        result=object(),
    )
    controller = WorkspaceController(workspace)
    results = []
    result_seen_by_structure_observers = []
    controller.resultChanged.connect(results.append)
    controller.structureChanged.connect(
        lambda _atoms: result_seen_by_structure_observers.append(
            workspace.result
        )
    )

    controller.replace_structure(new_atoms)

    assert workspace.atoms is new_atoms
    assert workspace.potential_path is None
    assert workspace.result is None
    assert workspace.input_parameters is parameters
    assert workspace.directory == "calculation"
    assert results == [None]
    assert result_seen_by_structure_observers == [None]


def test_replacing_input_parameters_invalidates_only_result():
    atoms = Atoms("Fe")
    parameters = object()
    workspace = WorkspaceState(
        atoms=atoms,
        input_parameters=object(),
        directory="calculation",
        potential_path="Fe.pot",
        result=object(),
    )
    controller = WorkspaceController(workspace)

    controller.replace_input_parameters(parameters)

    assert workspace.atoms is atoms
    assert workspace.potential_path == "Fe.pot"
    assert workspace.input_parameters is parameters
    assert workspace.directory == "calculation"
    assert workspace.result is None


def test_controller_loads_structure_and_document_metadata(tmp_path, monkeypatch):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    path = tmp_path / "Fe.pot"
    reads = []
    monkeypatch.setattr(
        "guy4ase.gui.application.workspace_controller.ase_read",
        lambda value: reads.append(value) or atoms,
    )
    parameters = object()
    controller = WorkspaceController(
        WorkspaceState(input_parameters=parameters, result=object())
    )

    loaded = controller.load_structure(path)

    assert loaded is atoms
    assert reads == [path.resolve()]
    assert controller.workspace.atoms is atoms
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.potential_path == str(path.resolve())
    assert controller.workspace.result is None
    assert controller.workspace.input_parameters is parameters


def test_loading_nonpotential_structure_drops_old_potential_source(
    tmp_path, monkeypatch
):
    atoms = Atoms("Cu")
    path = tmp_path / "Cu.xyz"
    monkeypatch.setattr(controller_module, "ase_read", lambda _path: atoms)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            potential_path="Fe.pot",
            result=object(),
        )
    )

    controller.load_structure(path)

    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path is None
    assert controller.workspace.result is None


def test_controller_loads_input_parameters_and_directory(tmp_path, monkeypatch):
    path = tmp_path / "Fe.inp"
    parameters = object()
    monkeypatch.setattr(
        controller_module.InputParameters,
        "from_file",
        staticmethod(lambda value: parameters),
    )
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=object(),
            potential_path="Fe.pot",
            result=object(),
        )
    )

    loaded = controller.load_input_parameters(path)

    assert loaded is parameters
    assert controller.workspace.input_parameters is parameters
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.result is None
    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path == "Fe.pot"


def test_controller_saves_current_documents(tmp_path, monkeypatch):
    structure_path = tmp_path / "Fe.xyz"
    input_path = tmp_path / "Fe.inp"
    atoms = Atoms("Fe")
    input_writes = []
    parameters = SimpleNamespace(
        to_file=lambda path: input_writes.append(path)
    )
    structure_writes = []
    monkeypatch.setattr(
        controller_module,
        "ase_write",
        lambda path, value: structure_writes.append((path, value)),
    )
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, input_parameters=parameters)
    )

    assert controller.save_structure(structure_path) == structure_path.resolve()
    assert controller.save_input_parameters(input_path) == input_path.resolve()
    assert structure_writes == [(structure_path.resolve(), atoms)]
    assert input_writes == [input_path.resolve()]


def test_restart_scf_is_a_document_operation_and_invalidates_result():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        )
    )
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, result=object())
    )

    controller.restart_scf()

    assert atoms.potential.SCF_INFO.SCFSTATUS == "START"
    assert controller.workspace.result is None


def _result(tmp_path):
    result = SimpleNamespace(
        files={"output": "Fe.out", "converged": "Fe.pot"},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    return result


def test_calculation_result_loads_potential_and_publishes_atoms(tmp_path, monkeypatch):
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    potential.touch()
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    monkeypatch.setattr(
        "guy4ase.gui.application.workspace_controller.Potential.from_file",
        lambda path: SimpleNamespace(atoms=atoms),
    )
    controller = WorkspaceController()
    result = _result(tmp_path)

    adoption = controller.adopt_calculation_result(result)

    assert adoption.output_path == output
    assert adoption.potential_path == potential
    assert adoption.potential_error is None
    assert controller.workspace.result is result
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path == str(potential.resolve())


def test_calculation_result_keeps_current_atoms_when_potential_loading_fails(
    tmp_path, monkeypatch
):
    potential = tmp_path / "Fe.pot"
    potential.touch()
    error = ValueError("broken potential")

    def fail(_path):
        raise error

    monkeypatch.setattr(
        "guy4ase.gui.application.workspace_controller.Potential.from_file",
        fail,
    )
    current_atoms = Atoms("Cu")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=current_atoms,
            potential_path="Cu.pot",
            directory=str(tmp_path),
        )
    )
    result = _result(tmp_path)

    adoption = controller.adopt_calculation_result(result)

    assert adoption.potential_error is error
    assert controller.workspace.result is result
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.atoms is current_atoms
    assert controller.workspace.potential_path == "Cu.pot"


def test_calculation_result_without_potential_keeps_current_atoms(tmp_path):
    current_atoms = Atoms("Cu")
    result = SimpleNamespace(
        files={"output": "Fe.out"},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    workspace = WorkspaceState(
        atoms=current_atoms,
        potential_path="Cu.pot",
        directory=str(tmp_path),
    )
    controller = WorkspaceController(workspace)

    adoption = controller.adopt_calculation_result(result)

    assert adoption.potential_path is None
    assert adoption.potential_error is None
    assert workspace.result is result
    assert workspace.atoms is current_atoms
    assert workspace.potential_path == "Cu.pot"


def test_external_result_without_potential_clears_old_structure(
    tmp_path, monkeypatch
):
    output = tmp_path / "external.out"
    result = SimpleNamespace(files={}, directory=str(tmp_path))
    monkeypatch.setattr(
        controller_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Fe"),
        potential_path="Fe.pot",
        result=object(),
    )
    controller = WorkspaceController(workspace)

    adoption = controller.load_result(output)

    assert adoption.output_path == output.resolve()
    assert adoption.potential_path is None
    assert adoption.potential_error is None
    assert workspace.result is result
    assert workspace.atoms is None
    assert workspace.potential_path is None


def test_external_result_with_unreadable_potential_clears_old_structure(
    tmp_path, monkeypatch
):
    output = tmp_path / "external.out"
    potential = tmp_path / "Fe.pot"
    potential.touch()
    result = _result(tmp_path)
    error = ValueError("broken potential")
    monkeypatch.setattr(
        controller_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    monkeypatch.setattr(
        controller_module.Potential,
        "from_file",
        staticmethod(lambda _path: (_ for _ in ()).throw(error)),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Cu"),
        potential_path="Cu.pot",
    )
    controller = WorkspaceController(workspace)

    adoption = controller.load_result(output)

    assert adoption.potential_path == potential.resolve()
    assert adoption.potential_error is error
    assert workspace.result is result
    assert workspace.atoms is None
    assert workspace.potential_path is None


def test_external_result_with_potential_replaces_old_structure(
    tmp_path, monkeypatch
):
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    potential.touch()
    result = _result(tmp_path)
    result_atoms = Atoms("Fe")
    monkeypatch.setattr(
        controller_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    monkeypatch.setattr(
        controller_module.Potential,
        "from_file",
        staticmethod(lambda _path: SimpleNamespace(atoms=result_atoms)),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Cu"),
        potential_path="Cu.pot",
    )
    controller = WorkspaceController(workspace)

    adoption = controller.load_result(output)

    assert adoption.potential_error is None
    assert workspace.result is result
    assert workspace.atoms is result_atoms
    assert workspace.potential_path == str(potential.resolve())


def test_successful_file_flow_updates_history(tmp_path, monkeypatch):
    path = tmp_path / "Fe.cif"
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(controller, "load_structure", lambda _path: atoms)

    assert file_flows.load_structure(controller, history, path, object())

    assert history.paths("structure") == (str(path),)


def test_failed_file_flow_does_not_update_history(tmp_path, monkeypatch):
    path = tmp_path / "broken.cif"
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")

    def fail(_path):
        raise ValueError("broken")

    monkeypatch.setattr(controller, "load_structure", fail)
    monkeypatch.setattr(file_flows.QMessageBox, "critical", lambda *args: None)

    assert not file_flows.load_structure(
        controller, history, path, object()
    )
    assert history.paths("structure") == ()


def test_file_chooser_and_recent_use_the_same_load_function(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.cif"
    path.touch()
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    calls = []

    def load(*args):
        calls.append(args)
        return True

    monkeypatch.setattr(file_flows, "load_structure", load)
    monkeypatch.setattr(
        file_flows.QFileDialog,
        "getOpenFileName",
        lambda *args: (str(path), ""),
    )

    assert file_flows.choose_and_load_structure(
        controller, history, object()
    )
    assert file_flows.open_recent(
        controller, history, "structure", path, object()
    )
    assert len(calls) == 2


def test_loading_unknown_structure_from_file_warns_but_keeps_it(
    tmp_path, monkeypatch
):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 8.0), pbc=(True, True, False))
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(controller, "load_structure", lambda _path: atoms)
    warnings = []
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    assert file_flows.load_structure(
        controller, history, tmp_path / "layer.xyz", object()
    )

    assert [title for title, _message in warnings] == [
        "Unknown Structure Type"
    ]


@pytest.mark.parametrize(
    "function, selection_name",
    [
        (structure_flows.create_structure_from_database, "chain_dialogs"),
        (structure_flows.download_structure, "select_online_structure"),
    ],
)
def test_loading_unknown_structure_from_database_warns(
    monkeypatch, function, selection_name
):
    atoms = Atoms("Fe", pbc=False)
    controller = WorkspaceController()
    warnings = []
    monkeypatch.setattr(
        structure_flows,
        selection_name,
        lambda *args, **kwargs: atoms,
    )
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append(title),
    )

    assert function(controller, object()) is atoms
    assert controller.workspace.atoms is atoms
    assert warnings == ["Unknown Structure Type"]


def test_run_window_lifetime_is_owned_by_its_qt_parent(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        calculation_flow.SprkkrRunWindow,
        "_start",
        lambda self, inputs: None,
    )
    parent = QWidget()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=object(),
            directory=str(tmp_path),
        )
    )
    history = RecentFiles(tmp_path / "recent.json")

    window = calculation_flow.run_calculation(controller, history, parent)
    assert window is not None
    assert window.parent() is parent
    reference = weakref.ref(window)
    del window
    gc.collect()
    assert reference() is not None

    reference().close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    deleted = reference()
    assert deleted is None or sip.isdeleted(deleted)


def test_calculation_flow_adopts_result_and_remembers_output(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        calculation_flow.SprkkrRunWindow,
        "_start",
        lambda self, inputs: None,
    )
    output = tmp_path / "Fe.out"
    result = object()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=object(),
            directory=str(tmp_path),
        )
    )
    monkeypatch.setattr(
        controller,
        "adopt_calculation_result",
        lambda value: ResultAdoption(output_path=output),
    )
    history = RecentFiles(tmp_path / "recent.json")
    parent = QWidget()
    window = calculation_flow.run_calculation(controller, history, parent)

    window._on_finished(result)

    assert history.paths("output") == (str(output),)
    window.close()


def test_run_worker_finishes_and_releases_thread(tmp_path):
    script = textwrap.dedent(
        f"""
        from ase import Atoms
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QWidget
        from guy4ase.gui.dialogs import run_calculation as run_dialog

        result = object()

        class Process:
            def run(self):
                return result

            def stop_the_process(self):
                pass

        class Calculator:
            def calculate(self, **_kwargs):
                return Process()

        run_dialog.SPRKKR = Calculator
        application = QApplication([])
        application.setQuitOnLastWindowClosed(False)
        parent = QWidget()
        finished = []
        window = run_dialog.SprkkrRunWindow(
            Atoms("Fe"),
            object(),
            {str(tmp_path)!r},
            parent=parent,
            on_finished=finished.append,
        )

        for _attempt in range(100):
            application.processEvents()
            if not window._thread.isRunning():
                break
            QTest.qWait(10)

        assert finished == [result]
        assert not window._thread.isRunning()
        window.close()
        application.processEvents()
        """
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("action", ["data", "edit"])
def test_result_payload_actions_use_the_shared_executor(
    monkeypatch, action
):
    payload = object()
    parent = object()
    opened = []

    class Value:
        name = "value"
        display_name = "Value"

        def __call__(self):
            return payload

        def data(self):
            return payload

    monkeypatch.setattr(
        object_view,
        "show_readonly_object_dialog",
        lambda value, *, title, parent: opened.append(
            (value, title, parent)
        ),
    )

    object_view.execute_value_action(Value(), action, parent)

    assert opened == [(payload, "View Value", parent)]
