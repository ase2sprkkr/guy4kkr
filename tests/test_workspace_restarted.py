from pathlib import Path
from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


def _scf_atoms(status="CONVERGED"):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(
        SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
    )
    return atoms


def _loaded_result(task, atoms):
    return LoadedResult(
        result=SimpleNamespace(task_name=task),
        output_path=None,
        potential_path=Path("Fe.pot"),
        atoms=atoms,
        potential_error=None,
        directory=None,
    )


def test_restarted_overrides_atoms_convergence_but_keeps_auto_detection_default():
    atoms = _scf_atoms()
    workspace = WorkspaceState(atoms=atoms)

    assert workspace.scf_status() == "CONVERGED"
    assert workspace.is_scf_converged()

    workspace.restarted = True

    assert workspace.scf_status() == "START"
    assert not workspace.is_scf_converged()


def test_confirmed_structure_edit_marks_workspace_restarted():
    atoms = _scf_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=atoms))

    change = controller.apply_structure_edit(
        lambda current: current,
        expected_generation=controller.generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.workspace.restarted
    assert not controller.workspace.is_scf_converged()


def test_restart_scf_marks_workspace_restarted_even_if_atoms_still_have_data():
    atoms = _scf_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=atoms))

    change = controller.restart_scf(expected_generation=controller.generation)

    assert change is DocumentChange.APPLIED
    assert controller.workspace.restarted
    assert controller.workspace.scf_status() == "START"
    assert not controller.workspace.is_scf_converged()


def test_adopting_scf_result_with_new_potential_clears_restart_override():
    controller = WorkspaceController(
        WorkspaceState(atoms=_scf_atoms(), restarted=True)
    )
    new_atoms = _scf_atoms()

    adoption = controller.adopt_calculation_result(
        _loaded_result("SCF", new_atoms),
        expected_generation=controller.generation,
    )

    assert adoption.adopted
    assert controller.workspace.atoms is new_atoms
    assert not controller.workspace.restarted
    assert controller.workspace.is_scf_converged()


def test_scf_result_without_new_potential_keeps_restart_override():
    controller = WorkspaceController(
        WorkspaceState(atoms=_scf_atoms(), restarted=True)
    )

    adoption = controller.adopt_calculation_result(
        _loaded_result("SCF", None),
        expected_generation=controller.generation,
    )

    assert adoption.adopted
    assert controller.workspace.restarted
    assert not controller.workspace.is_scf_converged()


def test_non_scf_result_does_not_clear_restart_override():
    controller = WorkspaceController(
        WorkspaceState(atoms=_scf_atoms(), restarted=True)
    )

    adoption = controller.adopt_calculation_result(
        _loaded_result("DOS", _scf_atoms()),
        expected_generation=controller.generation,
    )

    assert adoption.adopted
    assert controller.workspace.restarted


def test_external_result_starts_new_document_without_restart_override():
    controller = WorkspaceController(
        WorkspaceState(atoms=_scf_atoms(), restarted=True)
    )

    adoption = controller.adopt_external_result(
        _loaded_result("DOS", _scf_atoms()),
        expected_generation=controller.generation,
    )

    assert adoption.adopted
    assert not controller.workspace.restarted
