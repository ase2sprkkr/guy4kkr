from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import EmptySpheresState, WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


def _latest_state_result(controller: WorkspaceController):
    record = controller.result_store.latest_result_for_state(controller.state_id)
    assert record is not None
    return record


def test_empty_sphere_search_state_allows_repeated_failed_search():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    assert workspace.empty_spheres_action() == "add"

    controller = WorkspaceController(workspace)
    generation = controller.generation
    state_id = controller.state_id
    change = controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.empty_spheres == EmptySpheresState(count=0)
    assert workspace.empty_spheres_added == 0
    assert workspace.empty_spheres_action() == "recalculate"
    record = _latest_state_result(controller)
    assert record.result == EmptySpheresResult(found=0)
    assert record.input_state_id == state_id
    assert record.output_state_id is None
    assert controller.state_id == state_id
    assert controller.generation == generation


def test_empty_sphere_update_publishes_found_count_and_new_state():
    original = Atoms("Fe")
    workspace = WorkspaceState(atoms=original, potential_path="Fe.pot")
    controller = WorkspaceController(workspace)
    published = []
    controller.resultChanged.connect(published.append)
    generation = controller.generation
    structure_id = controller.structure_id
    input_state_id = controller.state_id

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
    record = _latest_state_result(controller)
    assert record.result == EmptySpheresResult(found=1)
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert published == [record.result]
    assert workspace.potential_path is None
    assert controller.generation == generation.next()


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
    assert _latest_state_result(controller).result == EmptySpheresResult(found=0)

    controller.replace_input_parameters(object())
    assert workspace.empty_spheres is state

    result = SimpleNamespace(task_name="dos")
    adoption = controller.adopt_external_result(
        LoadedResult(
            result=result,
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=None,
        )
    )

    assert adoption.record is not None
    assert adoption.record.result is result
    assert _latest_state_result(controller).result == EmptySpheresResult(found=0)
    assert workspace.empty_spheres is state
    assert dict(workspace.empty_spheres.parameters) == search_parameters


def test_empty_sphere_flow_prefills_parameters_from_workspace_state(monkeypatch):
    from guy4ase.gui.flows import structures

    search_parameters = {"max_radius": 1.4, "mesh": (18, 20, 22)}
    workspace = WorkspaceState(
        atoms=Atoms("Fe"),
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


def test_use_for_new_calculation_keeps_density_and_assigns_new_state():
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        ),
        sprkkr_is_scf_converged=lambda: True,
    )
    empty_spheres = EmptySpheresState(
        3, {"min_radius": 0.8, "mesh": (20, 20, 20)}
    )
    workspace = WorkspaceState(
        atoms=atoms,
        potential_path="Fe.pot",
        empty_spheres=empty_spheres,
    )
    controller = WorkspaceController(workspace)
    generation = controller.generation
    previous_state_id = controller.state_id
    previous_lineage = controller.result_store.state(previous_state_id).lineage_id

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
    assert controller.state_id != previous_state_id
    state = controller.result_store.state(controller.state_id)
    assert state.parent_id == previous_state_id
    assert state.lineage_id != previous_lineage
    assert controller.generation == generation.next()


def test_preexisting_vacuum_site_suppresses_add_but_known_spheres_can_recalculate():
    workspace = WorkspaceState(atoms=Atoms("X"))
    assert workspace.empty_spheres_action() is None

    workspace.empty_spheres = EmptySpheresState(1)
    assert workspace.empty_spheres_action() == "recalculate"
