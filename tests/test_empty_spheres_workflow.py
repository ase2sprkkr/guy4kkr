from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import EmptySpheresState, WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    DocumentChange,
    EmptySpheresAction,
    WorkspaceController,
)


def test_empty_sphere_search_state_allows_repeated_failed_search():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    controller = WorkspaceController(workspace)
    assert controller.empty_spheres_action() is EmptySpheresAction.ADD

    provenance = controller.structure_provenance
    input_state_id = controller.state_id
    change = controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_provenance=provenance,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.empty_spheres == EmptySpheresState(count=0)
    assert workspace.empty_spheres_added == 0
    assert controller.empty_spheres_action() is EmptySpheresAction.RECALCULATE
    first_record = controller.result_history.results[0]
    assert first_record.result == EmptySpheresResult(found=0)
    assert first_record.input_state_id == input_state_id
    assert first_record.output_state_id == controller.state_id
    first_output_state_id = controller.state_id
    assert first_output_state_id != input_state_id
    first_state = controller.result_history.state(first_output_state_id)
    assert first_state.parent_id == input_state_id
    assert first_state.empty_spheres == workspace.empty_spheres
    assert controller.structure_provenance is provenance

    def repeat_search(atoms, previous_count):
        assert previous_count == 0
        return atoms, 0, False

    change = controller.update_empty_spheres(
        repeat_search,
        expected_provenance=provenance,
    )

    assert change is DocumentChange.APPLIED
    assert len(controller.result_history.results) == 2
    second_record = controller.result_history.results[0]
    assert second_record.result == EmptySpheresResult(found=0)
    assert second_record.input_state_id == first_output_state_id
    assert second_record.output_state_id == controller.state_id
    assert controller.state_id != first_output_state_id
    second_state = controller.result_history.state(controller.state_id)
    assert second_state.parent_id == first_output_state_id
    assert second_state.empty_spheres == workspace.empty_spheres
    assert controller.structure_provenance is provenance


def test_empty_sphere_update_mutates_owned_atoms_in_place_and_creates_provenance():
    original = Atoms("Fe")
    workspace = WorkspaceState(atoms=original)
    controller = WorkspaceController(workspace)
    published = []
    controller.resultChanged.connect(published.append)
    provenance = controller.structure_provenance
    structure_id = controller.structure_id
    input_state_id = controller.state_id

    def add_one(atoms, _previous):
        assert atoms is original
        atoms += Atoms("X")
        return atoms, 1, True

    change = controller.update_empty_spheres(
        add_one,
        expected_provenance=provenance,
    )

    assert change is DocumentChange.APPLIED
    assert workspace.atoms is original
    assert len(original) == 2
    assert workspace.empty_spheres == EmptySpheresState(count=1)
    assert controller.structure_provenance != provenance
    record = controller.result_history.results[0]
    assert record.result == EmptySpheresResult(found=1)
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert published == [record.result]
    assert workspace.potential_path is None


def test_empty_sphere_state_keeps_search_parameters_across_later_results():
    workspace = WorkspaceState(atoms=Atoms("Fe"))
    controller = WorkspaceController(workspace)
    search_parameters = {"min_radius": 0.7, "mesh": (20, 22, 24)}

    controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_provenance=controller.structure_provenance,
        parameters=search_parameters,
    )

    state = workspace.empty_spheres
    assert state is not None
    assert dict(state.parameters) == search_parameters
    assert controller.result_history.results[0].result == EmptySpheresResult(found=0)

    assert controller.structure_id is not None
    assert controller.state_id is not None
    assert controller.structure_provenance is not None
    request = CalculationRequest(
        atoms=workspace.atoms,
        structure_provenance=controller.structure_provenance,
        input_parameters=object(),
        directory="",
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )
    controller.replace_input_parameters(object())
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
        request=request,
    )

    assert controller.result_history.results[0].result is result
    assert controller.result_history.results[1].result == EmptySpheresResult(found=0)
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


def test_use_for_new_calculation_keeps_structure_and_assigns_new_state():
    atoms = Atoms("Fe")
    empty_spheres = EmptySpheresState(
        3, {"min_radius": 0.8, "mesh": (20, 20, 20)}
    )
    workspace = WorkspaceState(
        atoms=atoms,
        empty_spheres=empty_spheres,
    )
    controller = WorkspaceController(workspace)
    provenance = controller.structure_provenance
    previous_state_id = controller.state_id

    change = controller.use_for_new_calculation(
        expected_state_id=previous_state_id
    )

    assert change is DocumentChange.APPLIED
    assert workspace.atoms is atoms
    assert workspace.structure_provenance is provenance
    assert workspace.restarted
    assert workspace.empty_spheres is empty_spheres
    assert workspace.empty_spheres_added == 3
    assert controller.state_id != previous_state_id
    assert controller.result_history.state(controller.state_id).parent_id == previous_state_id


def test_preexisting_vacuum_site_suppresses_add_but_known_spheres_can_recalculate():
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("X")))
    assert controller.empty_spheres_action() is None

    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("X"),
            empty_spheres=EmptySpheresState(1),
        )
    )
    assert controller.empty_spheres_action() is EmptySpheresAction.RECALCULATE
