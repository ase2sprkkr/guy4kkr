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


def _results(history):
    return tuple(record.result for record in history)


def test_result_history_is_independent_and_not_bounded_to_ten(tmp_path):
    controller = _controller(tmp_path)
    results = [SimpleNamespace(task_name="dos") for _ in range(12)]

    for result in results:
        request = controller.create_calculation_request()
        adoption = controller.adopt_calculation_result(_loaded(result), request=request)
        assert adoption.adopted
        assert not adoption.workspace_updated

    assert _results(controller.result_history) == tuple(reversed(results))
    assert len(controller.result_history) == 12


def test_input_and_structure_changes_do_not_delete_results(tmp_path):
    controller = _controller(tmp_path)
    first_structure_id = controller.structure_id
    result = SimpleNamespace(task_name="dos")
    request = controller.create_calculation_request()
    controller.adopt_calculation_result(_loaded(result), request=request)

    controller.replace_input_parameters(_Parameters(2))
    controller.replace_structure(Atoms("Ni"))

    assert _results(controller.result_history) == (result,)
    assert controller.result_history[0].structure_id == first_structure_id
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

    assert adoption.adopted
    assert not adoption.workspace_updated
    assert controller.atoms is original_atoms
    assert controller.state_id == original_state_id
    assert controller.result_history[0].result is external
    assert controller.result_history[0].output_state_id is not None


def test_active_scf_advances_workspace_but_late_sibling_does_not(tmp_path):
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
    state_b = controller.state_id
    assert controller.potential_path == str(tmp_path / "pb.pot_new")

    request_c = controller.create_calculation_request()
    result_c = SimpleNamespace(task_name="scf")
    atoms_c = Atoms("Fe")
    adoption_c = controller.adopt_calculation_result(
        _loaded(result_c, atoms=atoms_c, potential_path=tmp_path / "pc.pot_new"),
        request=request_c,
    )
    assert adoption_c.workspace_updated
    state_c = controller.state_id
    assert state_c != state_b

    result_a = SimpleNamespace(task_name="scf")
    atoms_a = Atoms("Fe")
    adoption_a = controller.adopt_calculation_result(
        _loaded(result_a, atoms=atoms_a, potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )

    assert adoption_a.adopted
    assert not adoption_a.workspace_updated
    assert controller.state_id == state_c
    assert controller.atoms is atoms_c
    assert controller.potential_path == str(tmp_path / "pc.pot_new")
    assert _results(controller.result_history) == (result_a, result_c, result_b)


def test_new_calculation_assigns_new_identity_while_reusing_potential(tmp_path):
    controller = _controller(tmp_path, potential_path="seed.pot")
    previous_state = controller.state_id
    previous_structure = controller.structure_id

    controller.use_for_new_calculation(expected_generation=controller.generation)

    assert controller.structure_id == previous_structure
    assert controller.state_id != previous_state
    assert controller.potential_path == "seed.pot"
    assert controller.result_store.state(controller.state_id).parent_id == previous_state


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
    )

    record = controller.result_history[0]
    assert record.result == EmptySpheresResult(found=1)
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert controller.result_store.state(controller.state_id).parent_id == input_state_id
    assert controller.potential_path is None


def test_empty_spheres_without_structure_change_records_result_only(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    state_id = controller.state_id

    controller.update_empty_spheres(
        lambda atoms, _previous: (atoms, 0, False),
        expected_generation=controller.generation,
    )

    record = controller.result_history[0]
    assert record.result == EmptySpheresResult(found=0)
    assert record.input_state_id == state_id
    assert record.output_state_id is None
    assert controller.state_id == state_id
    assert controller.potential_path == "Fe.pot"


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
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=None,
    )
    newest_record = store.add_result(
        newest,
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=None,
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )

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


def test_result_selector_shows_branch_nodes_only_after_real_fork():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, root_state = store.new_structure_state(Atoms("Fe"), potential_path="p0")

    first = store.add_result(
        _ui_result("scf", "a"),
        structure_id=structure_id,
        input_state_id=root_state,
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pa",
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_results(store)
    structure = widget._selector.topLevelItem(0)
    assert structure.childCount() == 1
    assert not structure.child(0).text(0).startswith("Branch")

    second = store.add_result(
        _ui_result("scf", "b"),
        structure_id=structure_id,
        input_state_id=root_state,
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pb",
    )
    widget.set_results(store)
    structure = widget._selector.topLevelItem(0)
    labels = {structure.child(i).text(0) for i in range(structure.childCount())}
    assert labels == {"Branch 1", "Branch 2"}
    assert store.branch_path(first) == (1,)
    assert store.branch_path(second) == (2,)
    widget.close()
