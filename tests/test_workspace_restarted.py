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


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


class _Status:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class _ScfInfo:
    def __init__(self, status):
        self._status = _Status(status)

    @property
    def SCFSTATUS(self):
        return self._status

    @SCFSTATUS.setter
    def SCFSTATUS(self, value):
        self._status.value = value


def _scf_atoms(status="CONVERGED"):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(SCF_INFO=_ScfInfo(status))
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


def _controller(*, restarted=True):
    return WorkspaceController(
        WorkspaceState(
            atoms=_scf_atoms("START" if restarted else "CONVERGED"),
            input_parameters=_Parameters(),
            directory="calculation",
            restarted=restarted,
        )
    )


def test_restart_marker_does_not_override_real_scf_status():
    atoms = _scf_atoms()
    workspace = WorkspaceState(atoms=atoms)

    assert workspace.scf_status() == "CONVERGED"
    assert workspace.is_scf_converged()

    workspace.restarted = True

    assert workspace.scf_status() == "CONVERGED"
    assert workspace.is_scf_converged()

    atoms.potential.SCF_INFO.SCFSTATUS = "START"

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
    assert controller.restarted
    assert not controller.is_scf_converged()


def test_use_for_new_calculation_restarts_attached_potential():
    atoms = _scf_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    previous_state_id = controller.state_id

    change = controller.use_for_new_calculation(
        expected_generation=controller.generation
    )

    assert change is DocumentChange.APPLIED
    assert controller.atoms is atoms
    assert atoms.potential.SCF_INFO.SCFSTATUS() == "START"
    assert controller.restarted
    assert controller.scf_status() == "START"
    assert not controller.is_scf_converged()
    assert controller.state_id != previous_state_id


def test_active_scf_result_with_new_potential_clears_restart_override():
    controller = _controller()
    request = controller.create_calculation_request()
    new_atoms = _scf_atoms()

    adoption = controller.record_finished_calculation(
        _loaded_result("SCF", new_atoms),
        request=request,
    )

    assert adoption.workspace_updated
    assert controller.atoms is new_atoms
    assert not controller.restarted
    assert controller.is_scf_converged()


def test_scf_result_without_new_potential_keeps_restart_override():
    controller = _controller()
    request = controller.create_calculation_request()

    adoption = controller.record_finished_calculation(
        _loaded_result("SCF", None),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.restarted
    assert controller.scf_status() == "START"
    assert not controller.is_scf_converged()


def test_non_scf_result_does_not_clear_restart_override():
    controller = _controller()
    request = controller.create_calculation_request()

    adoption = controller.record_finished_calculation(
        _loaded_result("DOS", _scf_atoms()),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.restarted
    assert controller.scf_status() == "START"


def test_external_result_does_not_clear_restart_override():
    controller = _controller()

    adoption = controller.adopt_external_result(
        _loaded_result("DOS", _scf_atoms()),
    )

    assert not adoption.workspace_updated
    assert controller.restarted
    assert controller.scf_status() == "START"
