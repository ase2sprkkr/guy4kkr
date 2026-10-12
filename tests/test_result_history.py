from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import Generation, ResultRecord, WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


def _loaded(result, *, atoms=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=None,
        atoms=atoms,
        potential_error=None,
        directory=None,
    )


def _results(history):
    return tuple(record.result for record in history)


def test_calculation_result_history_is_newest_first_and_bounded():
    controller = WorkspaceController()
    results = [SimpleNamespace(task_name="scf") for _ in range(12)]

    for result in results:
        adoption = controller.adopt_calculation_result(
            _loaded(result),
            expected_major=controller.generation.major,
        )
        assert adoption.adopted
        assert controller.result_history[0].generation == controller.generation

    assert controller.result is results[-1]
    assert _results(controller.result_history) == tuple(
        reversed(results[-10:])
    )
    assert all(record.current for record in controller.result_history)
    assert tuple(
        record.generation for record in controller.result_history
    ) == tuple(
        Generation(controller.generation.major, minor)
        for minor in range(
            controller.generation.minor,
            controller.generation.minor - len(controller.result_history),
            -1,
        )
    )


def test_input_change_preserves_history_but_marks_it_stale():
    controller = WorkspaceController()
    result = SimpleNamespace(task_name="scf")
    controller.adopt_calculation_result(
        _loaded(result),
        expected_major=controller.generation.major,
    )
    result_generation = controller.result_history[0].generation

    controller.replace_input_parameters(object())

    assert controller.result is None
    assert _results(controller.result_history) == (result,)
    record = controller.result_history[0]
    assert record.generation == result_generation
    assert not record.current
    assert record.generation.major != controller.generation.major


def test_structure_change_clears_history_after_current_result_is_invalidated():
    controller = WorkspaceController()
    result = SimpleNamespace(task_name="scf")
    controller.adopt_calculation_result(
        _loaded(result),
        expected_major=controller.generation.major,
    )

    controller.replace_input_parameters(object())
    assert controller.result is None
    assert _results(controller.result_history) == (result,)
    assert controller.result_history[0].stale

    controller.replace_structure(Atoms("Fe"))
    assert controller.result_history == ()


def test_use_for_new_calculation_preserves_stale_result_history():
    result = SimpleNamespace(task_name="scf")
    atoms = SimpleNamespace(
        potential=SimpleNamespace(
            SCF_INFO=SimpleNamespace(SCFSTATUS="CONVERGED")
        ),
        sprkkr_is_scf_converged=lambda: True,
    )
    workspace = WorkspaceState(
        atoms=atoms,
        result=result,
        potential_path="Fe.pot",
    )
    controller = WorkspaceController(workspace)

    controller.use_for_new_calculation(
        expected_generation=controller.generation
    )

    assert workspace.result is None
    assert _results(workspace.result_history) == (result,)
    assert workspace.result_history[0].stale


def test_external_result_starts_new_current_history():
    old = SimpleNamespace(task_name="scf")
    external = SimpleNamespace(task_name="dos")
    workspace = WorkspaceState(result=old)
    controller = WorkspaceController(workspace)

    adoption = controller.adopt_external_result(
        _loaded(external),
        expected_generation=controller.generation,
    )

    assert adoption.adopted
    assert workspace.result is external
    assert _results(workspace.result_history) == (external,)
    record = workspace.result_history[0]
    assert record.current
    assert record.generation == controller.generation


def test_empty_sphere_result_replaces_history_when_structure_changes():
    old = SimpleNamespace(task_name="scf")
    workspace = WorkspaceState(atoms=Atoms("Fe"), result=old)
    controller = WorkspaceController(workspace)

    def add_one(atoms, _previous):
        atoms += Atoms("X")
        return atoms, 1, True

    controller.update_empty_spheres(
        add_one,
        expected_generation=controller.generation,
    )

    assert workspace.result == EmptySpheresResult(found=1)
    assert _results(workspace.result_history) == (workspace.result,)
    assert workspace.result_history[0].current
    assert workspace.result_history[0].generation == controller.generation


def test_empty_sphere_result_is_added_when_structure_does_not_change():
    old = SimpleNamespace(task_name="scf")
    atoms = Atoms("Fe")
    workspace = WorkspaceState(atoms=atoms, result=old)
    controller = WorkspaceController(workspace)
    generation = controller.generation

    controller.update_empty_spheres(
        lambda current, _previous: (current, 0, False),
        expected_generation=generation,
    )

    assert workspace.result == EmptySpheresResult(found=0)
    assert _results(workspace.result_history) == (workspace.result, old)
    assert all(record.current for record in workspace.result_history)
    assert controller.generation == generation.next_minor()
    assert workspace.result_history[0].generation == controller.generation
    assert workspace.result_history[1].generation == generation


class _Value:
    info = ""

    def __init__(self, name):
        self.display_name = name

    def value_label(self):
        return self.display_name

    def actions(self):
        return ()


def test_result_selector_is_newest_first_and_switches_displayed_result():
    _application = QApplication.instance() or QApplication([])
    newest = SimpleNamespace(
        task_name="scf",
        output_file="new.out",
        output_values={"value": _Value("new")},
    )
    older = SimpleNamespace(
        task_name="dos",
        output_file="old.out",
        output_values={"value": _Value("old")},
    )
    newest_record = ResultRecord(newest, Generation(1, 1))
    older_record = ResultRecord(older, Generation(1, 0))
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )

    widget.set_results((newest_record, older_record))

    assert widget._selector.count() == 2
    assert widget._selector.itemText(0) == "Latest: SCF — new.out"
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "new"

    widget._selector.setCurrentIndex(1)
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "old"

    # Refreshing the same history keeps the user's selection.
    widget.set_results((newest_record, older_record))
    assert widget._selector.currentIndex() == 1

    # A newly added result selects the newest item.
    latest = SimpleNamespace(
        task_name="jxc",
        output_file="latest.out",
        output_values={"value": _Value("latest")},
    )
    latest_record = ResultRecord(latest, Generation(1, 2))
    widget.set_results((latest_record, newest_record, older_record))
    assert widget._selector.currentIndex() == 0
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "latest"
    widget.close()


def test_result_selector_marks_historical_result_as_stale():
    _application = QApplication.instance() or QApplication([])
    result = SimpleNamespace(
        task_name="scf",
        output_file="old.out",
        output_values={"value": _Value("old")},
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )

    widget.set_results((ResultRecord(result, Generation(0, 0), current=False),))

    assert widget._selector.itemText(0) == "Latest (stale): SCF — old.out"
    widget.close()
