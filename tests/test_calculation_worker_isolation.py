from __future__ import annotations

from ase import Atoms
from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.run_calculation import _SprkkrRunWorker


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def test_worker_lazy_promotion_does_not_mutate_workspace_atoms(tmp_path):
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    request = controller.create_calculation_request()

    worker = _SprkkrRunWorker(request)
    execution_atoms = worker._request.atoms

    assert request.atoms is atoms
    assert controller.atoms is atoms
    assert execution_atoms is not atoms

    SPRKKRAtoms.promote_ase_atoms(execution_atoms)
    execution_atoms.sites

    assert type(controller.atoms) is Atoms
    assert SPRKKRAtoms.sites_array_name not in controller.atoms.arrays


def test_worker_copy_owns_independent_sprkkr_site_state(tmp_path):
    atoms = SPRKKRAtoms("Fe2", positions=((0, 0, 0), (1, 0, 0)), symmetry=False)
    atoms.sites[1].site_type = atoms.sites[0].site_type
    original_site_type = atoms.sites[0].site_type

    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    worker = _SprkkrRunWorker(controller.create_calculation_request())
    copied = worker._request.atoms

    assert copied is not atoms
    assert copied.sites[0].site_type is copied.sites[1].site_type
    assert copied.sites[0].site_type is not original_site_type
    assert copied.sites[0].site_type.atoms is copied
    assert original_site_type.atoms is atoms
