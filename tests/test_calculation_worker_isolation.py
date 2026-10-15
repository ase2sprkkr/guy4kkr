from __future__ import annotations

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def _window(controller: WorkspaceController) -> SprkkrRunWindow:
    _application = QApplication.instance() or QApplication([])
    return SprkkrRunWindow(
        controller.atoms,
        controller.input_parameters,
        controller.directory,
        controller.create_run_provenance(),
    )


def test_execution_lazy_promotion_does_not_mutate_workspace_atoms(tmp_path):
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    window = _window(controller)
    execution_atoms = window._atoms

    assert controller.atoms is atoms
    assert execution_atoms is not atoms

    SPRKKRAtoms.promote_ase_atoms(execution_atoms)
    execution_atoms.sites

    assert type(controller.atoms) is Atoms
    assert SPRKKRAtoms.sites_array_name not in controller.atoms.arrays
    window.close()


def test_execution_copy_owns_independent_sprkkr_site_state(tmp_path):
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
    window = _window(controller)
    copied = window._atoms

    assert copied is not atoms
    assert copied.sites[0].site_type is copied.sites[1].site_type
    assert copied.sites[0].site_type is not original_site_type
    assert copied.sites[0].site_type.atoms is copied
    assert original_site_type.atoms is atoms
    window.close()
