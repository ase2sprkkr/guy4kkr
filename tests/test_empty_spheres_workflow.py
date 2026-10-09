from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


def test_empty_sphere_search_state_hides_repeated_failed_search():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    assert workspace.empty_spheres_action() == "add"

    controller = WorkspaceController(workspace)
    generation = controller.generation
    change = controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0),
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.empty_spheres_added == 0
    assert workspace.empty_spheres_action() is None
    assert controller.generation == generation


def test_use_for_new_calculation_keeps_density_and_marks_restart():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        ),
        sprkkr_is_scf_converged=lambda: True,
    )
    workspace = WorkspaceState(
        atoms=atoms,
        result=object(),
        potential_path="Fe.pot",
        empty_spheres_added=3,
    )
    controller = WorkspaceController(workspace)
    generation = controller.generation

    change = controller.use_for_new_calculation(
        expected_generation=generation
    )

    assert change is DocumentChange.APPLIED
    assert atoms.potential.SCF_INFO.SCFSTATUS == "START"
    assert workspace.restarted
    assert not workspace.is_scf_converged()
    assert workspace.empty_spheres_added == 3
    assert workspace.potential_path == "Fe.pot"
    assert workspace.result is None
    assert controller.generation == generation + 1


def test_preexisting_vacuum_site_suppresses_add_but_known_spheres_can_recalculate():
    workspace = WorkspaceState(atoms=Atoms("X"))
    assert workspace.empty_spheres_action() is None

    workspace.empty_spheres_added = 1
    assert workspace.empty_spheres_action() == "recalculate"
