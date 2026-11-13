from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.gui.application import result_loading
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import files as file_flows


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def test_potential_loader_attaches_exact_parsed_potential(tmp_path, monkeypatch):
    path = tmp_path / "Fe.pot"
    path.touch()
    atoms = SPRKKRAtoms.promote_ase_atoms(Atoms("Fe"))
    potential = SimpleNamespace(atoms=atoms)
    calls = []

    monkeypatch.setattr(
        result_loading.Potential,
        "from_file",
        staticmethod(lambda value: calls.append(value) or potential),
    )

    loaded_atoms = result_loading.load_potential_atoms(path)

    assert calls == [str(path.resolve())]
    assert loaded_atoms is atoms
    assert atoms.has_potential()
    assert atoms.potential is potential
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


def test_result_state_restart_decision_uses_atoms_not_path(tmp_path):
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
        atoms=atoms,
        potential_path=None,
        produced_by_result_id=None,
    )
    result = controller.result_store.add_result(
        SimpleNamespace(task_name="scf"),
        structure_id=controller.structure_id,
        input_state_id=child,
        atoms=atoms,
        input_parameters=_Parameters(),
        directory=str(tmp_path),
    )

    controller.use_result_state(result.id)

    assert controller.atoms is atoms
    assert controller.potential_path is None
    assert not controller.restarted
