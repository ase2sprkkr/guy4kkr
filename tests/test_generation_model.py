from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import (
    CalculationState,
    Generation,
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


def _result(task_name):
    return SimpleNamespace(task_name=task_name, produces_potential=False)


def _controller(tmp_path):
    return WorkspaceController(
        WorkspaceState(
            calculation=CalculationState(
                atoms=Atoms("Fe"),
                input_parameters=_Parameters(),
            ),
            context=WorkspaceContext(directory=str(tmp_path)),
        )
    )


def _loaded(result, *, atoms=None, potential_path=None, directory=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=potential_path,
        atoms=atoms,
        potential_error=None,
        directory=directory,
    )


def test_generation_is_a_regular_value_type_without_integer_compatibility():
    generation = Generation(1)

    assert generation == Generation(1)
    assert hash(generation) == hash(Generation(1))
    assert {generation: "value"}[Generation(1)] == "value"
    assert generation != 1
    assert generation != (1,)


def test_controller_restores_workspace_generation():
    generation = Generation(8)
    workspace = WorkspaceState(generation=generation)

    controller = WorkspaceController(workspace)

    assert controller.generation == generation
    assert workspace.generation == generation


def test_directory_change_advances_calculation_generation(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation

    controller.change_directory(str(tmp_path / "other"))

    assert controller.generation == generation.next()


def test_project_selection_does_not_advance_calculation_generation(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation

    controller.set_active_project("project-17")

    assert controller.active_project_id == "project-17"
    assert controller.generation == generation


def test_result_publication_does_not_advance_workspace_generation(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation
    request = controller.create_calculation_request()
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(
        _loaded(result, directory=str(tmp_path)),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.generation == generation
    assert controller.result_store.results[0].result is result


def test_parallel_non_scf_results_are_both_recorded_without_touching_draft(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    first = _result("DOS")
    second = _result("BSF")

    controller.adopt_calculation_result(_loaded(first), request=request_a)
    controller.adopt_calculation_result(_loaded(second), request=request_b)

    assert controller.generation == generation
    assert tuple(record.result for record in controller.result_store.results[:2]) == (
        second,
        first,
    )


def test_result_completion_does_not_stale_pending_draft_operation(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation
    request = controller.create_calculation_request()
    controller.adopt_calculation_result(
        _loaded(_result("DOS")),
        request=request,
    )

    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED


def test_draft_change_still_rejects_delayed_draft_callback(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation

    controller.replace_input_parameters(_Parameters())
    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_generation=generation,
    )

    assert change is DocumentChange.STALE


def test_structure_change_does_not_reject_completed_job_from_history(tmp_path):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    old_structure_id = request.structure_id
    controller.replace_structure(Atoms("Cu"))
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(_loaded(result), request=request)

    assert not adoption.workspace_updated
    assert controller.result_store.results[0].result is result
    assert controller.result_store.results[0].structure_id == old_structure_id
    assert controller.atoms.get_chemical_symbols() == ["Cu"]
