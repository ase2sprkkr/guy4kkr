from pathlib import Path
from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import (
    CalculationState,
    WorkspaceContext,
    WorkspaceState,
)
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def _scf_atoms(status="CONVERGED"):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(
        SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status),
        is_scf_converged=lambda _atoms: status == "CONVERGED",
    )
    return atoms


def _loaded_result(task, atoms, *, provenance=None):
    result = SimpleNamespace(
        task_name=task,
        produces_potential=task.lower() == "scf",
    )
    if provenance is not None:
        result.provenance = provenance
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=Path("Fe.pot"),
        atoms=atoms,
        potential_error=None,
        directory="calculation",
        input_parameters=_Parameters(),
    )


def _controller(*, restarted=True):
    return WorkspaceController(
        WorkspaceState(
            calculation=CalculationState(
                atoms=_scf_atoms(),
                input_parameters=_Parameters(),
                restarted=restarted,
            ),
            context=WorkspaceContext(directory="calculation"),
        )
    )


def test_restarted_overrides_atoms_convergence_but_keeps_auto_detection_default():
    atoms = _scf_atoms()
    calculation = CalculationState(atoms=atoms)

    assert calculation.scf_status() == "CONVERGED"
    assert calculation.is_scf_converged()

    calculation.restarted = True

    assert calculation.scf_status() == "START"
    assert not calculation.is_scf_converged()


def test_confirmed_structure_edit_marks_workspace_restarted():
    atoms = _scf_atoms()
    controller = WorkspaceController(
        WorkspaceState(calculation=CalculationState(atoms=atoms))
    )

    change = controller.apply_structure_edit(
        lambda current: current,
        expected_generation=controller.generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.restarted
    assert not controller.is_scf_converged()


def test_use_for_new_calculation_marks_restart_without_touching_atoms():
    atoms = _scf_atoms()
    controller = WorkspaceController(
        WorkspaceState(calculation=CalculationState(atoms=atoms))
    )
    previous_state_id = controller.state_id

    change = controller.use_for_new_calculation(
        expected_generation=controller.generation
    )

    assert change is DocumentChange.APPLIED
    assert controller.atoms is atoms
    assert atoms.sprkkr_is_scf_converged()
    assert controller.restarted
    assert controller.scf_status() == "START"
    assert not controller.is_scf_converged()
    assert controller.state_id != previous_state_id


def test_active_scf_result_with_new_potential_clears_restart_override():
    controller = _controller()
    provenance = controller.create_run_provenance()
    new_atoms = _scf_atoms()

    adoption = controller.adopt_calculation_result(
        _loaded_result("SCF", new_atoms, provenance=provenance)
    )

    assert adoption.workspace_updated
    assert controller.atoms is new_atoms
    assert not controller.restarted
    assert controller.is_scf_converged()


def test_scf_result_without_new_potential_keeps_restart_override():
    controller = _controller()
    provenance = controller.create_run_provenance()

    adoption = controller.adopt_calculation_result(
        _loaded_result("SCF", None, provenance=provenance)
    )

    assert not adoption.workspace_updated
    assert controller.restarted
    assert not controller.is_scf_converged()


def test_non_scf_result_does_not_clear_restart_override():
    controller = _controller()
    provenance = controller.create_run_provenance()

    adoption = controller.adopt_calculation_result(
        _loaded_result("DOS", _scf_atoms(), provenance=provenance)
    )

    assert not adoption.workspace_updated
    assert controller.restarted


def test_external_result_does_not_clear_restart_override():
    controller = _controller()

    adoption = controller.adopt_external_result(
        _loaded_result("DOS", _scf_atoms()),
    )

    assert not adoption.workspace_updated
    assert controller.restarted
