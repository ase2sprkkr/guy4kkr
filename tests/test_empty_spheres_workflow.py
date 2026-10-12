from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
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
    assert workspace.result == EmptySpheresResult(found=0)
    assert controller.generation == generation


def test_empty_sphere_update_publishes_found_count_as_result():
    workspace = WorkspaceState(atoms=Atoms("Fe"), result=object())
    controller = WorkspaceController(workspace)
    published = []
    controller.resultChanged.connect(published.append)
    generation = controller.generation

    def add_one(atoms, _previous):
        updated = atoms.copy()
        updated += Atoms("X")
        return updated, 1

    change = controller.update_empty_spheres(
        add_one,
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.result == EmptySpheresResult(found=1)
    assert published == [workspace.result]
    assert controller.generation == generation + 1


def test_empty_sphere_result_keeps_search_parameters():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    controller = WorkspaceController(workspace)

    controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0),
        expected_generation=controller.generation,
        parameters={"min_radius": 0.7, "mesh": (20, 22, 24)},
    )

    assert isinstance(workspace.result, EmptySpheresResult)
    assert dict(workspace.result.parameters) == {
        "min_radius": 0.7,
        "mesh": (20, 22, 24),
    }


def test_use_for_new_calculation_keeps_density_and_marks_restart():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        ),
        sprkkr_is_scf_converged=lambda: True,
    )
    previous_result = object()
    workspace = WorkspaceState(
        atoms=atoms,
        result=previous_result,
        potential_path="Fe.pot",
        empty_spheres_added=3,
    )
    controller = WorkspaceController(workspace)
    generation = controller.generation

    change = controller.use_for_new_calculation(
        expected_generation=generation
    )

    assert change is DocumentChange.APPLIED
    assert workspace.atoms is atoms
    assert atoms.potential.SCF_INFO.SCFSTATUS == "CONVERGED"
    assert workspace.restarted
    assert not workspace.is_scf_converged()
    assert workspace.empty_spheres_added == 3
    assert workspace.potential_path == "Fe.pot"
    assert workspace.result is None
    assert workspace.result_history == (previous_result,)
    assert controller.generation == generation + 1


def test_preexisting_vacuum_site_suppresses_add_but_known_spheres_can_recalculate():
    workspace = WorkspaceState(atoms=Atoms("X"))
    assert workspace.empty_spheres_action() is None

    workspace.empty_spheres_added = 1
    assert workspace.empty_spheres_action() == "recalculate"
