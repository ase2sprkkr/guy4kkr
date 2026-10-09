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

from guy4ase.gui.application import result_loading as result_loading_module
from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import (
    LoadedResult,
    load_result,
    load_result_file,
)
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    ResultAdoption,
    WorkspaceController,
)
from guy4ase.gui.dialogs import object_view
from guy4ase.gui.dialogs.structures import build_2d as build_2d_dialog
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
    controller.change_directory("calculation")
    controller.replace_structure(atoms, potential_path="Fe.pot")
    controller.replace_input_parameters(parameters)
    controller.adopt_calculation_result(
        LoadedResult(
            result=result,
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=None,
        ),
        expected_generation=controller.generation,
    )

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
    directories = []
    controller.directoryChanged.connect(directories.append)

    controller.replace_input_parameters(
        parameters, directory="calculation"
    )

    assert workspace.atoms is atoms
    assert workspace.potential_path == "Fe.pot"
    assert workspace.input_parameters is parameters
    assert workspace.directory == "calculation"
    assert workspace.result is None
    assert directories == []


def test_changing_directory_invalidates_result_and_same_directory_is_noop():
    result = object()
    workspace = WorkspaceState(directory="first", result=result)
    controller = WorkspaceController(workspace)
    results = []
    directories = []
    controller.resultChanged.connect(results.append)
    controller.directoryChanged.connect(directories.append)
    generation = controller.generation

    controller.change_directory("next")

    assert workspace.directory == "next"
    assert workspace.result is None
    assert controller.generation == generation + 1
    assert results == [None]
    assert directories == ["next"]

    controller.change_directory("next")

    assert controller.generation == generation + 1
    assert results == [None]
    assert directories == ["next"]


@pytest.mark.parametrize("suffix", [".pot", ".pot_new"])
def test_structure_flow_loads_potential_and_document_metadata(
    tmp_path, monkeypatch, suffix
):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    path = tmp_path / f"Fe{suffix}"
    reads = []
    monkeypatch.setattr(
        file_flows,
        "ase_read",
        lambda value: reads.append(value) or atoms,
    )
    parameters = object()
    controller = WorkspaceController(
        WorkspaceState(input_parameters=parameters, result=object())
    )
    history = RecentFiles(tmp_path / "recent.json")

    loaded = file_flows.load_structure(controller, history, path, object())

    assert loaded
    assert reads == [path.resolve()]
    assert controller.workspace.atoms is atoms
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.potential_path == str(path.resolve())
    assert controller.workspace.result is None
    assert controller.workspace.input_parameters is parameters
    assert history.paths("structure") == (str(path),)


def test_loading_nonpotential_structure_drops_old_potential_source(
    tmp_path, monkeypatch
):
    atoms = Atoms("Cu", cell=(2.8, 2.8, 2.8), pbc=True)
    path = tmp_path / "Cu.xyz"
    monkeypatch.setattr(file_flows, "ase_read", lambda _path: atoms)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            potential_path="Fe.pot",
            result=object(),
        )
    )

    loaded = file_flows.load_structure(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        path,
        object(),
    )

    assert loaded
    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path is None
    assert controller.workspace.result is None


def test_input_flow_loads_parameters_and_directory(tmp_path, monkeypatch):
    path = tmp_path / "Fe.inp"
    parameters = object()
    monkeypatch.setattr(
        file_flows.InputParameters,
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
    history = RecentFiles(tmp_path / "recent.json")

    loaded = file_flows.load_input_parameters(
        controller, history, path, object()
    )

    assert loaded
    assert controller.workspace.input_parameters is parameters
    assert controller.workspace.directory == str(tmp_path.resolve())
    assert controller.workspace.result is None
    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path == "Fe.pot"
    assert history.paths("input") == (str(path),)


def test_input_flow_rejects_parameters_parsed_for_a_stale_document(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.inp"
    original_parameters = object()
    parsed_parameters = object()
    replacement_atoms = Atoms("Cu")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=original_parameters,
            directory="original",
        )
    )
    history = RecentFiles(tmp_path / "recent.json")

    def parse(_path):
        controller.replace_structure(replacement_atoms)
        return parsed_parameters

    monkeypatch.setattr(
        file_flows.InputParameters,
        "from_file",
        staticmethod(parse),
    )
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert not file_flows.load_input_parameters(
        controller, history, path, object()
    )
    assert controller.workspace.atoms is replacement_atoms
    assert controller.workspace.input_parameters is original_parameters
    assert controller.workspace.directory == "original"
    assert history.paths("input") == ()


def test_structure_save_runs_under_gate_and_updates_history(
    tmp_path, monkeypatch
):
    structure_path = tmp_path / "Fe.xyz"
    atoms = Atoms("Fe")
    structure_writes = []
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(structure_path), ""),
    )
    monkeypatch.setattr(
        file_flows,
        "ase_write",
        lambda path, value: structure_writes.append(
            (path, value, controller.structure_gate.locked())
        ),
    )

    assert file_flows.save_structure(controller, history, object())

    assert structure_writes == [(structure_path.resolve(), atoms, True)]
    assert history.paths("structure") == (str(structure_path),)


def test_failed_structure_save_does_not_update_history(tmp_path, monkeypatch):
    structure_path = tmp_path / "Fe.xyz"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(structure_path), ""),
    )
    monkeypatch.setattr(
        file_flows,
        "ase_write",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(file_flows.QMessageBox, "critical", lambda *_args: None)

    assert not file_flows.save_structure(controller, history, object())
    assert history.paths("structure") == ()


def test_restart_scf_is_a_document_operation_and_invalidates_result():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        )
    )
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, result=object())
    )

    generation = controller.generation
    restarted = controller.restart_scf(expected_generation=generation)

    assert restarted is DocumentChange.APPLIED
    assert atoms.potential.SCF_INFO.SCFSTATUS == "START"
    assert controller.workspace.result is None
    assert controller.generation == generation + 1

    restarted_again = controller.restart_scf(
        expected_generation=controller.generation
    )
    assert restarted_again is DocumentChange.APPLIED


def _result(tmp_path):
    result = SimpleNamespace(
        files={"output": "Fe.out", "converged": "Fe.pot"},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    return result


def test_result_loading_resolves_relative_artifacts_from_result_directory(
    tmp_path, monkeypatch
):
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    output = run_directory / "Fe.out"
    converged = run_directory / "Fe_converged.pot"
    fallback_potential = run_directory / "Fe.pot"
    converged.touch()
    fallback_potential.touch()
    atoms = Atoms("Fe")
    potential_reads = []
    result = SimpleNamespace(
        files={
            "output": output.name,
            "converged": converged.name,
            "potential": fallback_potential.name,
        },
        directory=str(run_directory),
        potential_filename="ignored.pot",
    )
    result.path_to = lambda key: result.files[key]
    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(
            lambda path: potential_reads.append(path)
            or SimpleNamespace(atoms=atoms)
        ),
    )

    loaded = load_result(
        result,
        fallback_directory=tmp_path / "unused-fallback",
    )

    assert loaded.output_path == output.resolve()
    assert loaded.potential_path == converged.resolve()
    assert loaded.atoms is atoms
    assert loaded.potential_error is None
    assert loaded.directory == str(run_directory.resolve())
    assert potential_reads == [str(converged.resolve())]


@pytest.mark.parametrize(
    ("files", "potential_filename", "expected_name"),
    [
        ({"potential": "registered.pot"}, "filename.pot", "registered.pot"),
        ({}, "filename.pot", "filename.pot"),
    ],
)
def test_result_loading_uses_potential_fallbacks_and_fallback_directory(
    tmp_path, monkeypatch, files, potential_filename, expected_name
):
    potential = tmp_path / expected_name
    potential.touch()
    atoms = Atoms("Fe")
    result = SimpleNamespace(
        files=files,
        directory=None,
        potential_filename=potential_filename,
    )
    result.path_to = lambda key: result.files[key]
    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(lambda _path: SimpleNamespace(atoms=atoms)),
    )

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path == potential.resolve()
    assert loaded.atoms is atoms
    assert loaded.potential_error is None


def test_result_loading_uses_output_file_before_explicit_output_fallback(
    tmp_path,
):
    result = SimpleNamespace(
        files={},
        directory=None,
        output_file="metadata.out",
    )

    loaded = load_result(
        result,
        fallback_directory=tmp_path,
        output_fallback=tmp_path / "external.out",
    )

    assert loaded.output_path == (tmp_path / "metadata.out").resolve()
    assert loaded.directory == str(tmp_path.resolve())


def test_result_loading_reports_a_potential_path_that_is_not_a_file(tmp_path):
    potential_directory = tmp_path / "potential.pot"
    potential_directory.mkdir()
    result = SimpleNamespace(
        files={"potential": potential_directory.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=None)

    assert loaded.potential_path == potential_directory.resolve()
    assert loaded.atoms is None
    assert isinstance(loaded.potential_error, IsADirectoryError)


def test_calculation_result_loads_potential_and_publishes_atoms(tmp_path, monkeypatch):
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    potential.touch()
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        lambda path: SimpleNamespace(atoms=atoms),
    )
    controller = WorkspaceController(
        WorkspaceState(directory=str(tmp_path.resolve()))
    )
    result = _result(tmp_path)
    loaded = load_result(result, fallback_directory=tmp_path)

    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=controller.generation
    )

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
        result_loading_module.Potential,
        "from_file",
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
    loaded = load_result(result, fallback_directory=tmp_path)

    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=controller.generation
    )

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
    loaded = load_result(result, fallback_directory=tmp_path)

    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=controller.generation
    )

    assert adoption.potential_path is None
    assert adoption.potential_error is None
    assert workspace.result is result
    assert workspace.atoms is current_atoms
    assert workspace.potential_path == "Cu.pot"


def test_calculation_result_with_missing_referenced_potential_keeps_atoms(
    tmp_path,
):
    current_atoms = Atoms("Cu")
    missing = tmp_path / "missing.pot"
    result = SimpleNamespace(
        files={"output": "Fe.out", "converged": missing.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    workspace = WorkspaceState(
        atoms=current_atoms,
        potential_path="Cu.pot",
        directory=str(tmp_path),
    )
    controller = WorkspaceController(workspace)
    loaded = load_result(result, fallback_directory=tmp_path)

    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=controller.generation
    )

    assert adoption.adopted
    assert adoption.potential_path == missing.resolve()
    assert isinstance(adoption.potential_error, FileNotFoundError)
    assert workspace.result is result
    assert workspace.atoms is current_atoms
    assert workspace.potential_path == "Cu.pot"


def test_external_result_without_potential_clears_old_structure(
    tmp_path, monkeypatch
):
    output = tmp_path / "external.out"
    result = SimpleNamespace(files={}, directory=str(tmp_path))
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Fe"),
        potential_path="Fe.pot",
        result=object(),
    )
    controller = WorkspaceController(workspace)
    loaded = load_result_file(output)

    adoption = controller.adopt_external_result(
        loaded, expected_generation=controller.generation
    )

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
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(lambda _path: (_ for _ in ()).throw(error)),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Cu"),
        potential_path="Cu.pot",
    )
    controller = WorkspaceController(workspace)
    loaded = load_result_file(output)

    adoption = controller.adopt_external_result(
        loaded, expected_generation=controller.generation
    )

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
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(lambda _path: SimpleNamespace(atoms=result_atoms)),
    )
    workspace = WorkspaceState(
        atoms=Atoms("Cu"),
        potential_path="Cu.pot",
    )
    controller = WorkspaceController(workspace)
    loaded = load_result_file(output)

    adoption = controller.adopt_external_result(
        loaded, expected_generation=controller.generation
    )

    assert adoption.potential_error is None
    assert workspace.result is result
    assert workspace.atoms is result_atoms
    assert workspace.potential_path == str(potential.resolve())


def test_result_parse_failure_leaves_workspace_and_generation_unchanged(
    tmp_path, monkeypatch
):
    atoms = Atoms("Cu")
    parameters = object()
    old_result = object()
    workspace = WorkspaceState(
        atoms=atoms,
        input_parameters=parameters,
        directory="original",
        potential_path="Cu.pot",
        result=old_result,
    )
    error = ValueError("broken output")

    controller = WorkspaceController(workspace)
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: (_ for _ in ()).throw(error)),
    )
    signals = []
    controller.structureChanged.connect(
        lambda value: signals.append(("structure", value))
    )
    controller.inputParametersChanged.connect(
        lambda value: signals.append(("input", value))
    )
    controller.directoryChanged.connect(
        lambda value: signals.append(("directory", value))
    )
    controller.resultChanged.connect(
        lambda value: signals.append(("result", value))
    )

    with pytest.raises(ValueError, match="broken output"):
        load_result_file(tmp_path / "broken.out")

    assert controller.generation == 0
    assert workspace.atoms is atoms
    assert workspace.input_parameters is parameters
    assert workspace.directory == "original"
    assert workspace.potential_path == "Cu.pot"
    assert workspace.result is old_result
    assert signals == []


def test_result_artifact_resolution_failure_leaves_workspace_unchanged(
    tmp_path, monkeypatch
):
    error = RuntimeError("broken artifact metadata")
    result = SimpleNamespace(
        files={"output": "Fe.out", "converged": "Fe.pot"},
        directory=str(tmp_path),
    )

    def fail_path_to(_key):
        raise error

    result.path_to = fail_path_to
    atoms = Atoms("Cu")
    workspace = WorkspaceState(
        atoms=atoms,
        directory="original",
        potential_path="Cu.pot",
        result=object(),
    )
    original_result = workspace.result
    controller = WorkspaceController(workspace)
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )

    with pytest.raises(RuntimeError, match="broken artifact metadata"):
        load_result_file(tmp_path / "Fe.out")

    assert controller.generation == 0
    assert workspace.atoms is atoms
    assert workspace.directory == "original"
    assert workspace.potential_path == "Cu.pot"
    assert workspace.result is original_result


def test_result_loading_has_no_workspace_side_effects(tmp_path, monkeypatch):
    output = tmp_path / "Fe.out"
    result = SimpleNamespace(files={}, directory=str(tmp_path))
    atoms = Atoms("Cu")
    parameters = object()
    current_result = object()
    workspace = WorkspaceState(
        atoms=atoms,
        input_parameters=parameters,
        directory="original",
        potential_path="Cu.pot",
        result=current_result,
    )
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )

    loaded = load_result_file(output)

    assert loaded.result is result
    assert workspace.atoms is atoms
    assert workspace.input_parameters is parameters
    assert workspace.directory == "original"
    assert workspace.potential_path == "Cu.pot"
    assert workspace.result is current_result


def test_missing_output_path_is_advisory_provenance(tmp_path):
    missing_output = tmp_path / "missing.out"
    result = SimpleNamespace(
        files={"output": missing_output.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.output_path == missing_output.resolve()
    assert not missing_output.exists()
    assert loaded.potential_error is None


def test_missing_referenced_potential_is_an_explicit_nonfatal_failure(
    tmp_path, monkeypatch
):
    output = tmp_path / "external.out"
    missing = tmp_path / "missing.pot"
    result = SimpleNamespace(
        files={"output": output.name, "converged": missing.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]
    workspace = WorkspaceState(
        atoms=Atoms("Cu"),
        potential_path="Cu.pot",
        result=object(),
    )
    controller = WorkspaceController(workspace)
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    loaded = load_result_file(output)

    adoption = controller.adopt_external_result(
        loaded, expected_generation=controller.generation
    )

    assert adoption.adopted
    assert adoption.potential_path == missing.resolve()
    assert isinstance(adoption.potential_error, FileNotFoundError)
    assert workspace.result is result
    assert workspace.atoms is None
    assert workspace.potential_path is None


def test_successful_result_load_is_one_observer_consistent_transition(
    tmp_path,
):
    output = tmp_path / "Fe.out"
    potential = tmp_path / "Fe.pot"
    result_atoms = Atoms("Fe")
    result = object()
    loaded = LoadedResult(
        result=result,
        output_path=output,
        potential_path=potential,
        atoms=result_atoms,
        potential_error=None,
        directory=str(tmp_path),
    )

    workspace = WorkspaceState(
        atoms=Atoms("Cu"), potential_path="Cu.pot", result=object()
    )
    controller = WorkspaceController(workspace)
    observed = []
    controller.structureChanged.connect(
        lambda atoms: observed.append(
            (
                atoms,
                workspace.result,
                workspace.directory,
                workspace.potential_path,
                controller.generation,
            )
        )
    )

    adoption = controller.adopt_external_result(
        loaded, expected_generation=controller.generation
    )

    assert adoption.adopted
    assert observed == [
        (
            result_atoms,
            result,
            str(tmp_path),
            str(potential),
            1,
        )
    ]


def test_successful_file_flow_updates_history(tmp_path, monkeypatch):
    path = tmp_path / "Fe.cif"
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows,
        "ase_read",
        lambda _source: atoms,
    )

    assert file_flows.load_structure(controller, history, path, object())

    assert history.paths("structure") == (str(path),)


def test_failed_file_flow_does_not_update_history(tmp_path, monkeypatch):
    path = tmp_path / "broken.cif"
    atoms = Atoms("Cu")
    result = object()
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Cu.pot", result=result)
    )
    history = RecentFiles(tmp_path / "recent.json")
    generation = controller.generation

    def fail(_path):
        raise ValueError("broken")

    monkeypatch.setattr(file_flows, "ase_read", fail)
    monkeypatch.setattr(file_flows.QMessageBox, "critical", lambda *args: None)

    assert not file_flows.load_structure(
        controller, history, path, object()
    )
    assert history.paths("structure") == ()
    assert controller.generation == generation
    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path == "Cu.pot"
    assert controller.workspace.result is result


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
    monkeypatch.setattr(
        file_flows,
        "ase_read",
        lambda _source: atoms,
    )
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


def test_build_2d_load_reads_only_atoms_without_workspace_side_effects(
    tmp_path, monkeypatch
):
    path = tmp_path / "right.pot"
    loaded_atoms = Atoms("Fe")
    workspace_atoms = Atoms("Cu")
    workspace = WorkspaceState(
        atoms=workspace_atoms,
        potential_path="Cu.pot",
        result=object(),
    )
    current_result = workspace.result
    reads = []
    assigned = []
    dialog = SimpleNamespace(
        _set_right_atoms=assigned.append,
        _set_status=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        build_2d_dialog.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(path), ""),
    )
    monkeypatch.setattr(
        build_2d_dialog,
        "ase_read",
        lambda value: reads.append(value) or loaded_atoms,
    )

    build_2d_dialog.Build2DStructureDialog._on_load_right(dialog)

    assert reads == [path.resolve()]
    assert assigned == [loaded_atoms]
    assert workspace.atoms is workspace_atoms
    assert workspace.potential_path == "Cu.pot"
    assert workspace.result is current_result


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
            input_parameters=SimpleNamespace(
                copy=lambda **_kwargs: object()
            ),
            directory=str(tmp_path),
        )
    )
    history = RecentFiles(tmp_path / "recent.json")
    active_runs = ActiveRunRegistry()

    window = calculation_flow.run_calculation(
        controller, history, active_runs, parent
    )
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
            input_parameters=SimpleNamespace(
                copy=lambda **_kwargs: object()
            ),
            directory=str(tmp_path),
        )
    )
    monkeypatch.setattr(
        controller,
        "adopt_calculation_result",
        lambda value, **_kwargs: ResultAdoption(output_path=output),
    )
    history = RecentFiles(tmp_path / "recent.json")
    active_runs = ActiveRunRegistry()
    parent = QWidget()
    window = calculation_flow.run_calculation(
        controller, history, active_runs, parent
    )

    window._on_finished(result)

    assert history.paths("output") == (str(output),)
    window.close()


def test_calculation_flow_reports_result_adoption_failure(
    tmp_path, monkeypatch
):
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        calculation_flow.SprkkrRunWindow,
        "_start",
        lambda self, inputs: None,
    )
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=SimpleNamespace(
                copy=lambda **_kwargs: object()
            ),
            directory=str(tmp_path),
        )
    )
    error = RuntimeError("broken artifact metadata")

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(controller, "adopt_calculation_result", fail)
    messages = []
    monkeypatch.setattr(
        calculation_flow.QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    history = RecentFiles(tmp_path / "recent.json")
    parent = QWidget()
    window = calculation_flow.run_calculation(
        controller, history, ActiveRunRegistry(), parent
    )

    window._on_finished(object())

    assert messages == [
        (
            "Result Adoption Error",
            (
                "The calculation finished, but its result could not be "
                "adopted:\nbroken artifact metadata"
            ),
        )
    ]
    assert history.paths("output") == ()
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
