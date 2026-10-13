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
    directory: str | None = None,
):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=Path(potential_path) if potential_path is not None else None,
        atoms=atoms,
        potential_error=None,
        directory=directory,
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


def _single_lineage_results(controller: WorkspaceController):
    store = controller.result_store
    structure_id = store.structures[0].id
    lineage_ids = store.lineage_ids(structure_id)
    assert len(lineage_ids) == 1
    return store.results_in_lineage(structure_id, lineage_ids[0])


def test_result_tree_is_independent_and_not_bounded_to_ten(tmp_path):
    controller = _controller(tmp_path)
    results = [SimpleNamespace(task_name="dos") for _ in range(12)]

    for result in results:
        request = controller.create_calculation_request()
        adoption = controller.record_finished_calculation(_loaded(result), request=request)
        assert not adoption.workspace_updated

    records = _single_lineage_results(controller)
    assert tuple(record.result for record in records) == tuple(results)
    assert len(controller.result_store) == 12


def test_input_and_structure_changes_do_not_delete_results(tmp_path):
    controller = _controller(tmp_path)
    first_structure_id = controller.structure_id
    result = SimpleNamespace(task_name="dos")
    request = controller.create_calculation_request()
    record = controller.record_finished_calculation(_loaded(result), request=request).record

    controller.replace_input_parameters(_Parameters(2))
    controller.replace_structure(Atoms("Ni"))

    assert record is not None
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
            directory=str(tmp_path),
        )
    )

    assert not adoption.workspace_updated
    assert controller.atoms is original_atoms
    assert controller.state_id == original_state_id
    assert adoption.record is not None
    assert adoption.record.result is external
    assert adoption.record.output_state_id is not None
    assert adoption.record.imported
    assert controller.result_store.imported_results(str(tmp_path)) == (adoption.record,)


def test_active_scf_advances_workspace_but_late_sibling_stays_in_old_lineage(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()

    result_b = SimpleNamespace(task_name="scf")
    atoms_b = Atoms("Fe")
    adoption_b = controller.record_finished_calculation(
        _loaded(result_b, atoms=atoms_b, potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
    assert adoption_b.workspace_updated
    state_b = controller.state_id

    request_c = controller.create_calculation_request()
    result_c = SimpleNamespace(task_name="scf")
    atoms_c = Atoms("Fe")
    adoption_c = controller.record_finished_calculation(
        _loaded(result_c, atoms=atoms_c, potential_path=tmp_path / "pc.pot_new"),
        request=request_c,
    )
    assert adoption_c.workspace_updated
    state_c = controller.state_id
    assert state_c != state_b
    assert controller.result is result_c

    result_a = SimpleNamespace(task_name="scf")
    atoms_a = Atoms("Fe")
    adoption_a = controller.record_finished_calculation(
        _loaded(result_a, atoms=atoms_a, potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )

    assert not adoption_a.workspace_updated
    assert controller.state_id == state_c
    assert controller.atoms is atoms_c
    assert controller.potential_path == str(tmp_path / "pc.pot_new")
    assert controller.result is result_c
    store = controller.result_store
    assert store.lineage_id_for_result(adoption_b.record) == store.lineage_id_for_result(
        adoption_c.record
    )
    assert store.lineage_id_for_result(adoption_a.record) != store.lineage_id_for_result(
        adoption_c.record
    )


def test_use_for_new_calculation_starts_new_lineage_and_is_write_barrier(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    old_request = controller.create_calculation_request()
    old_state = controller.state_id
    old_lineage = controller.result_store.state(old_state).lineage_id

    controller.use_for_new_calculation(expected_generation=controller.generation)
    restart_state = controller.state_id
    restart_lineage = controller.result_store.state(restart_state).lineage_id
    assert restart_lineage != old_lineage
    assert controller.potential_path == "p0.pot"

    late_result = SimpleNamespace(task_name="scf")
    late = controller.record_finished_calculation(
        _loaded(late_result, atoms=Atoms("Fe"), potential_path=tmp_path / "old.pot_new"),
        request=old_request,
    )

    assert not late.workspace_updated
    assert controller.state_id == restart_state
    assert controller.restarted
    assert controller.potential_path == "p0.pot"
    assert controller.result_store.lineage_id_for_result(late.record) == old_lineage

    new_request = controller.create_calculation_request()
    new_result = SimpleNamespace(task_name="scf")
    new = controller.record_finished_calculation(
        _loaded(new_result, atoms=Atoms("Fe"), potential_path=tmp_path / "new.pot_new"),
        request=new_request,
    )
    assert new.workspace_updated
    assert controller.result_store.lineage_id_for_result(new.record) == restart_lineage


def test_use_result_state_explicitly_switches_to_historical_potential(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    result_a = SimpleNamespace(task_name="scf")
    result_b = SimpleNamespace(task_name="scf")

    a = controller.record_finished_calculation(
        _loaded(result_a, atoms=Atoms("Fe"), potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )
    assert a.workspace_updated
    b = controller.record_finished_calculation(
        _loaded(result_b, atoms=Atoms("Fe"), potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
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
    )

    records = _single_lineage_results(controller)
    record = records[-1]
    assert record.result == EmptySpheresResult(found=1)
    assert record.task_name == "empty_spheres"
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert controller.result_store.state(controller.state_id).parent_id == input_state_id
    assert controller.potential_path is None


def test_empty_spheres_without_structure_change_does_not_change_workspace(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    state_id = controller.state_id
    generation = controller.generation
    atoms = controller.atoms

    controller.update_empty_spheres(
        lambda candidate, _previous: (candidate, 0, False),
        expected_generation=generation,
    )

    records = _single_lineage_results(controller)
    record = records[-1]
    assert record.result == EmptySpheresResult(found=0)
    assert record.task_name == "empty_spheres"
    assert record.input_state_id == state_id
    assert record.output_state_id is None
    assert controller.state_id == state_id
    assert controller.atoms is atoms
    assert controller.potential_path == "Fe.pot"
    assert controller.generation == generation


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


def _widget():
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
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
    widget = _widget()
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


def test_result_selector_projects_scf_empty_spheres_and_dependent_results():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, root = store.new_structure_state(Atoms("Fe"), potential_path="p0")

    first_scf = store.add_result(
        _ui_result("scf", "scf1"),
        structure_id=structure_id,
        input_state_id=root,
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory="run",
        output_atoms=Atoms("Fe"),
        output_potential_path="p1",
    )
    first_state = first_scf.output_state_id
    assert first_state is not None
    store.add_result(
        _ui_result("dos", "dos1"),
        structure_id=structure_id,
        input_state_id=first_state,
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory="run",
    )
    empty_spheres = store.add_result(
        EmptySpheresResult(found=2),
        structure_id=structure_id,
        input_state_id=first_state,
        atoms=Atoms("Fe"),
        input_parameters={},
        directory="run",
        output_atoms=Atoms("FeX2"),
        output_potential_path=None,
    )
    spheres_state = empty_spheres.output_state_id
    assert spheres_state is not None
    second_scf = store.add_result(
        _ui_result("scf", "scf2"),
        structure_id=structure_id,
        input_state_id=spheres_state,
        atoms=Atoms("FeX2"),
        input_parameters=object(),
        directory="run",
        output_atoms=Atoms("FeX2"),
        output_potential_path="p2",
    )
    second_state = second_scf.output_state_id
    assert second_state is not None
    store.add_result(
        _ui_result("bsf", "bsf2"),
        structure_id=structure_id,
        input_state_id=second_state,
        atoms=Atoms("FeX2"),
        input_parameters=object(),
        directory="run",
    )

    widget = _widget()
    widget.set_results(store)

    structure = widget._selector.topLevelItem(0)
    assert [structure.child(i).text(0).split(" — ", 1)[0] for i in range(3)] == [
        "SCF",
        "Empty spheres",
        "SCF",
    ]
    first_scf_item = structure.child(0)
    second_scf_item = structure.child(2)
    assert first_scf_item.childCount() == 1
    assert first_scf_item.child(0).text(0).startswith("DOS")
    assert second_scf_item.childCount() == 1
    assert second_scf_item.child(0).text(0).startswith("BSF")
    widget.close()


def test_imported_results_are_grouped_by_source_directory():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    directory = "/work/Fe/run1"

    first = store.add_external_result(
        _ui_result("scf", "scf"),
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=directory,
        output_path=Path(directory) / "scf.out",
        potential_path=Path(directory) / "Fe.pot",
        produces_state=True,
    )
    second = store.add_external_result(
        _ui_result("dos", "dos"),
        atoms=None,
        input_parameters=object(),
        directory=directory,
        output_path=Path(directory) / "dos.out",
        potential_path=None,
        produces_state=False,
    )

    assert store.imported_results(directory) == (first, second)

    widget = _widget()
    widget.set_results(store)

    assert widget._selector.topLevelItemCount() == 1
    directory_item = widget._selector.topLevelItem(0)
    assert directory_item.text(0) == directory
    assert directory_item.childCount() == 2
    assert directory_item.child(0).text(0).startswith("SCF")
    assert directory_item.child(1).text(0).startswith("DOS")
    widget.close()
