from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult, load_result
from guy4ase.gui.application.workspace import ResultRecord, WorkspaceState
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


def test_controller_restores_workspace_generation_and_current_provenance():
    generation = Generation(8, 3)
    result = SimpleNamespace(task_name="SCF")
    workspace = WorkspaceState(
        result=result,
        result_history=(ResultRecord(result, generation),),
        generation=generation,
    )

    controller = WorkspaceController(workspace)

    assert controller.generation == generation
    assert workspace.generation == generation
    assert controller.result_history[0].generation == generation
    assert controller.result_history[0].current


def test_controller_rejects_inconsistent_current_result_provenance():
    result = SimpleNamespace(task_name="SCF")
    workspace = WorkspaceState(
        result=result,
        result_history=(ResultRecord(result, Generation(8, 3)),),
        generation=Generation(8, 4),
    )

    with pytest.raises(ValueError, match="Current result provenance"):
        WorkspaceController(workspace)


def test_generation_major_and_minor_changes_have_distinct_semantics(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    initial = controller.generation
    assert initial == Generation(0, 0)

    result, loaded = _loaded(tmp_path, "first")
    adoption = controller.adopt_calculation_result(
        loaded, expected_major=initial.major
    )

    assert adoption.adopted
    assert controller.result is result
    assert controller.generation == initial.next_minor()
    assert controller.result_history[0].generation == controller.generation

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
        first_loaded, expected_major=source_generation.major
    )
    after_first = controller.generation
    second = controller.adopt_calculation_result(
        second_loaded, expected_major=source_generation.major
    )

    assert first.adopted
    assert second.adopted
    assert after_first == source_generation.next_minor()
    assert controller.generation == after_first.next_minor()
    assert controller.result is second_result
    records = controller.result_history[:2]
    assert tuple(record.result for record in records) == (
        second_result,
        first_result,
    )
    assert all(record.current for record in records)
    assert tuple(record.generation for record in records) == (
        controller.generation,
        after_first,
    )


def test_sibling_non_scf_result_cannot_roll_back_scf_workspace_state(tmp_path):
    source_atoms = Atoms("Fe")
    source_potential = tmp_path / "source.pot"
    controller = WorkspaceController(
        WorkspaceState(
            atoms=source_atoms,
            directory=str(tmp_path),
            potential_path=str(source_potential),
        )
    )
    source_generation = controller.generation

    scf_atoms = Atoms("Cu")
    scf_potential = tmp_path / "converged.pot"
    scf_result = SimpleNamespace(task_name="SCF")
    scf_loaded = LoadedResult(
        result=scf_result,
        output_path=None,
        potential_path=scf_potential,
        atoms=scf_atoms,
        potential_error=None,
        directory=str(tmp_path),
    )

    stale_atoms = Atoms("Ni")
    dos_result = SimpleNamespace(task_name="DOS")
    dos_loaded = LoadedResult(
        result=dos_result,
        output_path=None,
        potential_path=source_potential,
        atoms=stale_atoms,
        potential_error=None,
        directory=str(tmp_path),
    )

    scf_adoption = controller.adopt_calculation_result(
        scf_loaded, expected_major=source_generation.major
    )
    dos_adoption = controller.adopt_calculation_result(
        dos_loaded, expected_major=source_generation.major
    )

    assert scf_adoption.adopted
    assert dos_adoption.adopted
    assert controller.result is dos_result
    assert tuple(record.result for record in controller.result_history[:2]) == (
        dos_result,
        scf_result,
    )
    assert controller.atoms is scf_atoms
    assert controller.potential_path == str(scf_potential)


def test_result_minor_change_stales_full_revision_but_not_sibling_run(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), directory=str(tmp_path))
    )
    source_generation = controller.generation
    _result, loaded = _loaded(tmp_path, "first")
    assert controller.adopt_calculation_result(
        loaded, expected_major=source_generation.major
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
        loaded, expected_major=source_generation.major
    )

    assert not adoption.adopted
    assert controller.result is None
