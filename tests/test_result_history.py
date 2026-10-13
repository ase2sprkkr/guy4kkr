from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Parameters:
    def __init__(self, value=0):
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.value)


def _loaded(
    result,
    *,
    atoms=None,
    potential_path: str | Path | None = None,
    input_parameters=None,
):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=Path(potential_path) if potential_path is not None else None,
        atoms=atoms,
        potential_error=None,
        directory=None,
        input_parameters=input_parameters,
    )


def _controller(tmp_path, atoms=None, potential_path=None):
    return WorkspaceController(
        WorkspaceState(
            atoms=atoms or Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path=potential_path,
        )
    )


def test_result_store_is_independent_and_not_bounded_to_ten(tmp_path):
    controller = _controller(tmp_path)
    results = [SimpleNamespace(task_name="dos") for _ in range(12)]
    state_id = controller.state_id
    assert state_id is not None

    for result in results:
        request = controller.create_calculation_request()
        adoption = controller.adopt_calculation_result(_loaded(result), request=request)
        assert not adoption.workspace_updated

    records = controller.result_store.results_for_state(state_id)
    assert tuple(record.result for record in records) == tuple(results)
    assert len(controller.result_store) == 12
    assert not hasattr(controller, "result_history")
    assert not hasattr(controller.result_store, "results")


def test_input_and_structure_changes_do_not_delete_results(tmp_path):
    controller = _controller(tmp_path)
    first_structure_id = controller.structure_id
    result = SimpleNamespace(task_name="dos")
    request = controller.create_calculation_request()
    adoption = controller.adopt_calculation_result(_loaded(result), request=request)
    record = adoption.record
    assert record is not None

    controller.replace_input_parameters(_Parameters(2))
    controller.replace_structure(Atoms("Ni"))

    assert controller.result_store.result(record.id).result is result
    assert record.structure_id == first_structure_id
    assert controller.structure_id != first_structure_id


def test_external_result_is_recorded_without_replacing_workspace(tmp_path):
    controller = _controller(tmp_path, atoms=Atoms("Cu"), potential_path="current.pot")
    original_atoms = controller.atoms
    original_state_id = controller.state_id
    external_atoms = Atoms("Fe")
    external = SimpleNamespace(task_name="scf")

    adoption = controller.adopt_external_result(
        _loaded(
            external,
            atoms=external_atoms,
            potential_path=tmp_path / "external.pot_new",
            input_parameters=_Parameters(7),
        )
    )
    record = adoption.record
    assert record is not None

    assert not adoption.workspace_updated
    assert controller.atoms is original_atoms
    assert controller.state_id == original_state_id
    assert record.result is external
    assert record.output_state_id is not None
    assert record.imported


def test_active_scf_advances_workspace_but_late_sibling_stays_in_old_branch(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()

    result_b = SimpleNamespace(task_name="scf")
    atoms_b = Atoms("Fe")
    adoption_b = controller.adopt_calculation_result(
        _loaded(result_b, atoms=atoms_b, potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
    assert adoption_b.workspace_updated
    assert adoption_b.record is not None
    state_b = controller.state_id

    request_c = controller.create_calculation_request()
    result_c = SimpleNamespace(task_name="scf")
    atoms_c = Atoms("Fe")
    adoption_c = controller.adopt_calculation_result(
        _loaded(result_c, atoms=atoms_c, potential_path=tmp_path / "pc.pot_new"),
        request=request_c,
    )
    assert adoption_c.workspace_updated
    assert adoption_c.record is not None
    state_c = controller.state_id
    assert state_c != state_b
    assert controller.result is result_c

    result_a = SimpleNamespace(task_name="scf")
    atoms_a = Atoms("Fe")
    adoption_a = controller.adopt_calculation_result(
        _loaded(result_a, atoms=atoms_a, potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )
    assert adoption_a.record is not None

    assert not adoption_a.workspace_updated
    assert controller.state_id == state_c
    assert controller.atoms is atoms_c
    assert controller.potential_path == str(tmp_path / "pc.pot_new")
    assert controller.result is result_c
    state_of_b = controller.result_store.state(adoption_b.record.output_state_id)
    state_of_c = controller.result_store.state(adoption_c.record.output_state_id)
    state_of_a = controller.result_store.state(adoption_a.record.output_state_id)
    assert state_of_b.branch_id == state_of_c.branch_id
    assert state_of_a.branch_id != state_of_c.branch_id


def test_use_for_new_calculation_is_a_new_branch_and_write_barrier(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    old_request = controller.create_calculation_request()
    old_state = controller.state_id
    assert old_state is not None
    old_branch = controller.result_store.state(old_state).branch_id

    controller.use_for_new_calculation(expected_generation=controller.generation)
    restart_state = controller.state_id
    assert restart_state is not None
    restart_branch = controller.result_store.state(restart_state).branch_id
    assert restart_branch != old_branch
    assert controller.potential_path == "p0.pot"

    late_result = SimpleNamespace(task_name="scf")
    late = controller.adopt_calculation_result(
        _loaded(late_result, atoms=Atoms("Fe"), potential_path=tmp_path / "old.pot_new"),
        request=old_request,
    )
    assert late.record is not None

    assert not late.workspace_updated
    assert controller.state_id == restart_state
    assert controller.restarted
    assert controller.potential_path == "p0.pot"
    late_state = controller.result_store.state(late.record.output_state_id)
    assert late_state.branch_id == old_branch

    new_request = controller.create_calculation_request()
    new_result = SimpleNamespace(task_name="scf")
    new = controller.adopt_calculation_result(
        _loaded(new_result, atoms=Atoms("Fe"), potential_path=tmp_path / "new.pot_new"),
        request=new_request,
    )
    assert new.workspace_updated
    assert new.record is not None
    new_state = controller.result_store.state(new.record.output_state_id)
    assert new_state.branch_id == restart_branch


def test_use_result_state_explicitly_switches_to_historical_potential(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    result_a = SimpleNamespace(task_name="scf")
    result_b = SimpleNamespace(task_name="scf")

    a = controller.adopt_calculation_result(
        _loaded(result_a, atoms=Atoms("Fe"), potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )
    assert a.workspace_updated
    b = controller.adopt_calculation_result(
        _loaded(result_b, atoms=Atoms("Fe"), potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
    assert b.record is not None
    assert not b.workspace_updated
    assert controller.result is result_a

    controller.use_result_state(b.record.id)

    assert controller.state_id == b.record.output_state_id
    assert controller.potential_path == str(tmp_path / "pb.pot_new")
    assert controller.result is result_b


def test_empty_spheres_is_result_transition_within_same_structure(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    structure_id = controller.structure_id
    input_state_id = controller.state_id

    def add_one(atoms, _previous):
        atoms += Atoms("X")
        return atoms, 1, True

    controller.update_empty_spheres(
        add_one,
        expected_generation=controller.generation,
        parameters={"radius": 1.25},
    )

    record = controller.result_store.latest_result_for_state(controller.state_id)
    assert record is not None
    state = controller.result_store.state(controller.state_id)
    assert record.result == EmptySpheresResult(found=1)
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert state.parent_id == input_state_id
    assert state.empty_spheres == controller.empty_spheres
    assert dict(state.empty_spheres.parameters) == {"radius": 1.25}
    assert controller.potential_path is None


def test_empty_spheres_without_structure_change_creates_restorable_state(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    input_state_id = controller.state_id
    generation = controller.generation
    atoms = controller.atoms

    controller.update_empty_spheres(
        lambda candidate, _previous: (candidate, 0, False),
        expected_generation=generation,
        parameters={"method": "probe"},
    )

    record = controller.result_store.latest_result_for_state(controller.state_id)
    assert record is not None
    state = controller.result_store.state(controller.state_id)
    assert record.result == EmptySpheresResult(found=0)
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert controller.state_id != input_state_id
    assert controller.atoms is atoms
    assert state.structure_snapshot is not None
    assert controller.potential_path == "Fe.pot"
    assert state.potential_path == "Fe.pot"
    assert controller.generation != generation
    assert state.empty_spheres == controller.empty_spheres
    assert dict(state.empty_spheres.parameters) == {"method": "probe"}


def test_use_result_state_restores_empty_sphere_provenance(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")

    controller.update_empty_spheres(
        lambda candidate, _previous: (candidate, 0, False),
        expected_generation=controller.generation,
        parameters={"radius": 1.5, "grid": 24},
    )
    empty_spheres_record = controller.result_store.latest_result_for_state(
        controller.state_id
    )
    assert empty_spheres_record is not None
    empty_spheres_state_id = controller.state_id

    controller.replace_structure(Atoms("Ni"), potential_path="Ni.pot")
    assert controller.empty_spheres is None

    controller.use_result_state(empty_spheres_record.id)

    assert controller.state_id == empty_spheres_state_id
    assert controller.potential_path == "Fe.pot"
    assert controller.empty_spheres is not None
    assert controller.empty_spheres.count == 0
    assert dict(controller.empty_spheres.parameters) == {"radius": 1.5, "grid": 24}


class _Value:
    info = ""

    def __init__(self, name):
        self.display_name = name

    def value_label(self):
        return self.display_name

    def actions(self):
        return ()


def _ui_result(task, name):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{name}.out",
        output_values={"value": _Value(name)},
    )


def test_result_selector_groups_by_formula_and_switches_displayed_result():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)
    older = _ui_result("dos", "old")
    newest = _ui_result("jxc", "new")
    store.add_result(
        older,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
    )
    newest_record = store.add_result(
        newest,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_workspace_state(structure_id, state_id)
    widget.set_results(store)

    assert widget._selector.topLevelItemCount() == 1
    structure = widget._selector.topLevelItem(0)
    assert structure.text(0) == "Fe"
    assert structure.childCount() == 2
    assert widget._selected_result_id() == newest_record.id
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "new"

    widget._selector.setCurrentItem(structure.child(0))
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "old"
    widget.close()


def test_result_selector_does_not_expose_internal_branch_nodes():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, root_state = store.new_structure_state(Atoms("Fe"), potential_path="p0")

    first = store.add_result(
        _ui_result("scf", "a"),
        structure_id=structure_id,
        input_state_id=root_state,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pa",
    )
    second = store.add_result(
        _ui_result("scf", "b"),
        structure_id=structure_id,
        input_state_id=root_state,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pb",
    )
    assert first.output_state_id is not None
    assert second.output_state_id is not None
    assert store.state(first.output_state_id).branch_id != store.state(second.output_state_id).branch_id

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_results(store)
    structure = widget._selector.topLevelItem(0)
    assert structure.childCount() == 2
    assert all(
        not structure.child(index).text(0).startswith("Branch")
        for index in range(structure.childCount())
    )
    widget.close()
