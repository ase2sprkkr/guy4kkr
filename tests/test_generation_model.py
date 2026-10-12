from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import load_result
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    Generation,
    WorkspaceController,
)


def _loaded(tmp_path, name):
    result = SimpleNamespace(files={}, directory=str(tmp_path), name=name)
    return result, load_result(result, fallback_directory=tmp_path)


def test_generation_is_a_regular_value_type_without_integer_compatibility():
    generation = Generation(1, 0)

    assert generation == Generation(1, 0)
    assert hash(generation) == hash(Generation(1, 0))
    assert {generation: "value"}[Generation(1, 0)] == "value"
    assert generation != 1
    assert Generation(1, 1) != 1
    assert generation != (1, 0)


def test_generation_major_and_minor_changes_have_distinct_semantics(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    initial = controller.generation
    assert initial == Generation(0, 0)

    result, loaded = _loaded(tmp_path, "first")
    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=initial
    )

    assert adoption.adopted
    assert controller.workspace.result is result
    assert controller.generation == initial.next_minor()

    before_structure_change = controller.generation
    controller.replace_structure(Atoms("Cu"))
    assert controller.generation == before_structure_change.next_major()


def test_parallel_results_from_same_major_generation_are_both_adopted(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    source_generation = controller.generation
    first_result, first_loaded = _loaded(tmp_path, "first")
    second_result, second_loaded = _loaded(tmp_path, "second")

    first = controller.adopt_calculation_result(
        first_loaded, expected_generation=source_generation
    )
    after_first = controller.generation
    second = controller.adopt_calculation_result(
        second_loaded, expected_generation=source_generation
    )

    assert first.adopted
    assert second.adopted
    assert after_first == source_generation.next_minor()
    assert controller.generation == after_first.next_minor()
    assert controller.workspace.result is second_result
    assert controller.workspace.result_history[:2] == (
        second_result,
        first_result,
    )


def test_result_minor_change_stales_full_revision_but_not_sibling_run(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    source_generation = controller.generation
    _result, loaded = _loaded(tmp_path, "first")
    assert controller.adopt_calculation_result(
        loaded, expected_generation=source_generation
    ).adopted

    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_generation=source_generation,
    )

    assert change is DocumentChange.STALE


def test_major_change_rejects_calculation_result(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    source_generation = controller.generation
    _result, loaded = _loaded(tmp_path, "stale")

    controller.replace_structure(Atoms("Cu"))
    adoption = controller.adopt_calculation_result(
        loaded, expected_generation=source_generation
    )

    assert not adoption.adopted
    assert controller.workspace.result is None
