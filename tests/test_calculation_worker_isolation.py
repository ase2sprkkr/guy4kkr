from __future__ import annotations

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms

from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace import CalculationState, WorkspaceContext, WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def _workspace(atoms, tmp_path):
    return WorkspaceState(
        calculation=CalculationState(
            atoms=atoms,
            input_parameters=_Parameters(),
        ),
        context=WorkspaceContext(directory=str(tmp_path)),
    )


def test_request_snapshot_isolates_backend_mutation_from_workspace_atoms(tmp_path):
    atoms = Atoms("Fe")
    controller = WorkspaceController(_workspace(atoms, tmp_path))
    request = controller.create_calculation_request()

    assert controller.atoms is atoms
    assert request.atoms is not atoms

    execution = SprkkrExecution(request, _Cancellation())
    assert execution.request is request
    execution_atoms = execution.request.atoms

    SPRKKRAtoms.promote_ase_atoms(execution_atoms)
    execution_atoms.sites

    assert type(controller.atoms) is Atoms
    assert SPRKKRAtoms.sites_array_name not in controller.atoms.arrays


def test_request_snapshot_owns_independent_sprkkr_site_state(tmp_path):
    atoms = SPRKKRAtoms("Fe2", positions=((0, 0, 0), (1, 0, 0)), symmetry=False)
    atoms.sites[1].site_type = atoms.sites[0].site_type
    original_site_type = atoms.sites[0].site_type

    controller = WorkspaceController(_workspace(atoms, tmp_path))
    request = controller.create_calculation_request()
    execution = SprkkrExecution(request, _Cancellation())
    copied = request.atoms

    assert execution.request is request
    assert copied is not atoms
    assert copied.sites[0].site_type is copied.sites[1].site_type
    assert copied.sites[0].site_type is not original_site_type
    assert copied.sites[0].site_type.atoms is copied
    assert original_site_type.atoms is atoms
