from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import EmptySpheresState, WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


def test_empty_sphere_search_state_allows_repeated_failed_search():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    assert workspace.empty_spheres_action() == "add"

    controller = WorkspaceController(workspace)
    generation = controller.generation
    change = controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.empty_spheres == EmptySpheresState(count=0)
    assert workspace.empty_spheres_added == 0
    assert workspace.empty_spheres_action() == "recalculate"
    assert workspace.result == EmptySpheresResult(found=0)
    assert controller.generation == generation.next_minor()
    assert workspace.result_history[0].generation == controller.generation


def test_empty_sphere_update_publishes_found_count_as_result():
    original = Atoms("Fe")
    workspace = WorkspaceState(atoms=original, result=object())
    controller = WorkspaceController(workspace)
    published = []
    controller.resultChanged.connect(published.append)
    generation = controller.generation

    def add_one(atoms, _previous):
        assert atoms is not original
        atoms += Atoms("X")
        return atoms, 1, True

    change = controller.update_empty_spheres(
        add_one,
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.atoms is not original
    assert len(original) == 1
    assert len(workspace.atoms) == 2
    assert workspace.empty_spheres == EmptySpheresState(count=1)
    assert workspace.result == EmptySpheresResult(found=1)
    assert published == [workspace.result]
    assert controller.generation == generation.next_major()
    assert workspace.result_history[0].generation == controller.generation


def test_empty_sphere_state_keeps_search_parameters_across_later_results():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    controller = WorkspaceController(workspace)
    search_parameters = {"min_radius": 0.7, "mesh": (20, 22, 24)}

    controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_generation=controller.generation,
        parameters=search_parameters,
    )

    state = workspace.empty_spheres
    assert state is not None
    assert dict(state.parameters) == search_parameters
    assert workspace.result == EmptySpheresResult(found=0)

    controller.replace_input_parameters(object())
    assert workspace.result is None
    assert workspace.empty_spheres is state

    result = SimpleNamespace(task_name="dos")
    controller.adopt_calculation_result(
        LoadedResult(
            result=result,
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=None,
        ),
        expected_major=controller.generation.major,
    )

    assert workspace.result is result
    assert workspace.empty_spheres is state
    assert dict(workspace.empty_spheres.parameters) == search_parameters


def test_empty_sphere_flow_prefills_parameters_from_workspace_state(monkeypatch):
    from guy4ase.gui.flows import structures

    search_parameters = {"max_radius": 1.4, "mesh": (18, 20, 22)}
    workspace = WorkspaceState(
        atoms=Atoms("Fe"),
        result=SimpleNamespace(task_name="dos"),
        empty_spheres=EmptySpheresState(0, search_parameters),
    )
    controller = WorkspaceController(workspace)
    seen = []

    def select_parameters(*, initial, parent):
        seen.append(initial)
        return None

    monkeypatch.setattr(
        structures, "select_empty_spheres_parameters", select_parameters
    )

    assert not structures.update_empty_spheres(controller, None)
    assert len(seen) == 1
    assert dict(seen[0]) == search_parameters


def test_use_for_new_calculation_keeps_density_and_marks_restart():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        ),
        sprkkr_is_scf_converged=lambda: True,
    )
    previous_result = object()
    empty_spheres = EmptySpheresState(
        3, {"min_radius": 0.8, "mesh": (20, 20, 20)}
    )
    workspace = WorkspaceState(
        atoms=atoms,
        result=previous_result,
        potential_path="Fe.pot",
        empty_spheres=empty_spheres,
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
    assert workspace.empty_spheres is empty_spheres
    assert workspace.empty_spheres_added == 3
    assert workspace.potential_path == "Fe.pot"
    assert workspace.result is None
    assert len(workspace.result_history) == 1
    assert workspace.result_history[0].result is previous_result
    assert not workspace.result_history[0].current
    assert controller.generation == generation.next_major()


def test_preexisting_vacuum_site_suppresses_add_but_known_spheres_can_recalculate():
    workspace = WorkspaceState(atoms=Atoms("X"))
    assert workspace.empty_spheres_action() is None

    workspace.empty_spheres = EmptySpheresState(1)
    assert workspace.empty_spheres_action() == "recalculate"
