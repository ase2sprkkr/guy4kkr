from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms
from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.gui.application import result_loading
from guy4ase.gui.application import workspace_controller as workspace_controller_module
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    PotentialVersionChanged,
    WorkspaceController,
)
from guy4ase.gui.flows import files as file_flows


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def test_potential_loader_delegates_stable_read_to_ase2sprkkr(tmp_path, monkeypatch):
    path = tmp_path / "Fe.pot"
    path.touch()
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    potential = SimpleNamespace(atoms=atoms)
    calls = []

    def parse(value, *, check_file_unchanged=False):
        calls.append((value, check_file_unchanged))
        return potential

    monkeypatch.setattr(
        result_loading.Potential,
        "from_file",
        staticmethod(parse),
    )

    loaded_atoms = result_loading.load_potential_atoms(path)

    assert calls == [(str(path.resolve()), True)]
    assert loaded_atoms is atoms
    assert potential.atoms is atoms


def test_potential_structure_flow_uses_authoritative_potential_loader(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.pot_new"
    path.touch()
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    calls = []
    monkeypatch.setattr(
        file_flows,
        "load_potential_atoms",
        lambda value: calls.append(value) or atoms,
    )

    assert file_flows._read_structure_file(path) is atoms
    assert calls == [path]


def test_calculation_request_uses_atoms_not_potential_path(tmp_path):
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    potential = SimpleNamespace(atoms=atoms)
    atoms._potential = potential
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path="source-only.pot",
        )
    )

    request = controller.create_calculation_request()

    assert request.atoms is atoms
    assert request.atoms.potential is potential
    assert not hasattr(request, "potential_path")


def test_potless_historical_state_restores_structure_not_runtime_potential(tmp_path):
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    potential = SimpleNamespace(atoms=atoms)
    atoms._potential = potential
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path=None,
        )
    )
    parent = controller.state_id
    assert parent is not None
    child = controller.result_store.new_child_state(
        parent,
        potential_path=None,
        produced_by_result_id=None,
    )
    result = controller.result_store.add_result(
        SimpleNamespace(task_name="scf"),
        structure_id=controller.structure_id,
        input_state_id=child,
        input_parameters=_Parameters(),
        directory=str(tmp_path),
    )

    controller.replace_structure(Atoms("Cu"))
    controller.use_result_state(result.id)

    assert controller.atoms is not atoms
    assert controller.atoms.get_chemical_symbols() == ["Fe"]
    assert not getattr(controller.atoms, "has_potential", lambda: False)()
    assert controller.potential_path is None
    assert controller.restarted


def test_deleted_pot_backed_state_does_not_fall_back_to_retained_atoms(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.pot"
    path.write_text("historical potential")
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    potential = SimpleNamespace(atoms=atoms)
    atoms._potential = potential
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path=str(path),
        )
    )
    state_id = controller.state_id
    assert state_id is not None
    state = controller.result_store.state(state_id)
    assert state.structure_snapshot is None
    result = controller.result_store.add_result(
        SimpleNamespace(task_name="dos"),
        structure_id=controller.structure_id,
        input_state_id=state_id,
        input_parameters=_Parameters(),
        directory=str(tmp_path),
        potential_path=path,
    )

    controller.replace_structure(Atoms("Cu"))
    path.unlink()
    monkeypatch.setattr(
        workspace_controller_module,
        "load_potential_atoms",
        lambda *_args, **_kwargs: pytest.fail(
            "missing historical POTFIL must fail before parsing"
        ),
    )

    with pytest.raises(PotentialVersionChanged):
        controller.use_result_state(result.id)

    assert controller.atoms.get_chemical_symbols() == ["Cu"]


def test_unknown_current_potfil_version_stays_in_structure_lineage(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.pot"
    path.write_text("historical potential")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path=str(path),
        )
    )
    structure_id = controller.structure_id
    historical_state_id = controller.state_id
    assert structure_id is not None
    assert historical_state_id is not None
    historical_state = controller.result_store.state(historical_state_id)
    historical_version = historical_state.potential_version
    assert historical_version is not None

    result = controller.result_store.add_result(
        SimpleNamespace(task_name="dos"),
        structure_id=structure_id,
        input_state_id=historical_state_id,
        input_parameters=_Parameters(),
        directory=str(tmp_path),
        potential_path=path,
    )

    path.write_text("externally modified current potential is a different version")
    current_version = PotentialFileVersion.capture(path)
    assert current_version.available
    assert current_version != historical_version

    loaded_atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    calls = []

    def load(value):
        calls.append(value)
        return loaded_atoms

    monkeypatch.setattr(workspace_controller_module, "load_potential_atoms", load)

    controller.use_result_state(result.id, expected_potential=current_version)

    assert calls == [current_version.path]
    assert controller.atoms is loaded_atoms
    assert controller.structure_id == structure_id
    assert len(controller.result_store.structures) == 1
    assert controller.state_id != historical_state_id
    current_state = controller.result_store.state(controller.state_id)
    assert current_state.structure_id == structure_id
    assert current_state.parent_id == historical_state_id
    assert current_state.potential_version == current_version
    assert current_state.potential_source_result_id is None
    assert current_state.empty_spheres is None
    assert not controller.restarted
