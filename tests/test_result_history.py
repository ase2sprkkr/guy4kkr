from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
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


def test_calculation_result_history_is_newest_first_and_bounded():
    controller = WorkspaceController()
    results = [SimpleNamespace(task_name="scf") for _ in range(12)]

    for result in results:
        adoption = controller.adopt_calculation_result(
            _loaded(result),
            expected_generation=controller.generation,
        )
        assert adoption.adopted

    assert controller.workspace.result is results[-1]
    assert controller.workspace.result_history == tuple(
        reversed(results[-10:])
    )


def test_structure_change_clears_history_after_current_result_is_invalidated():
    controller = WorkspaceController()
    result = SimpleNamespace(task_name="scf")
    controller.adopt_calculation_result(
        _loaded(result),
        expected_generation=controller.generation,
    )

    controller.replace_input_parameters(object())
    assert controller.workspace.result is None
    assert controller.workspace.result_history == (result,)

    controller.replace_structure(Atoms("Fe"))
    assert controller.workspace.result_history == ()


def test_use_for_new_calculation_preserves_result_history():
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
    assert workspace.result_history == (result,)


def test_external_result_starts_new_history():
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
    assert workspace.result_history == (external,)


def test_empty_sphere_result_replaces_history_when_structure_changes():
    old = SimpleNamespace(task_name="scf")
    workspace = WorkspaceState(atoms=Atoms("Fe"), result=old)
    controller = WorkspaceController(workspace)

    def add_one(atoms, _previous):
        updated = atoms.copy()
        updated += Atoms("X")
        return updated, 1

    controller.update_empty_spheres(
        add_one,
        expected_generation=controller.generation,
    )

    assert workspace.result == EmptySpheresResult(found=1)
    assert workspace.result_history == (workspace.result,)


def test_empty_sphere_result_is_added_when_structure_does_not_change():
    old = SimpleNamespace(task_name="scf")
    atoms = Atoms("Fe")
    workspace = WorkspaceState(atoms=atoms, result=old)
    controller = WorkspaceController(workspace)

    controller.update_empty_spheres(
        lambda current, _previous: (current, 0),
        expected_generation=controller.generation,
    )

    assert workspace.result == EmptySpheresResult(found=0)
    assert workspace.result_history == (workspace.result, old)


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
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )

    widget.set_results((newest, older))

    assert widget._selector.count() == 2
    assert widget._selector.itemText(0) == "Latest: SCF — new.out"
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "new"

    widget._selector.setCurrentIndex(1)
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "old"

    # Refreshing the same history keeps the user's selection.
    widget.set_results((newest, older))
    assert widget._selector.currentIndex() == 1

    # A newly added result selects the newest item.
    latest = SimpleNamespace(
        task_name="jxc",
        output_file="latest.out",
        output_values={"value": _Value("latest")},
    )
    widget.set_results((latest, newest, older))
    assert widget._selector.currentIndex() == 0
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "latest"
    widget.close()
