from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application import workspace_controller as controller_module
from guy4ase.gui.application.result_store import PotentialFileVersion, ResultStore
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Value:
    info = ""
    display_name = "value"

    def value_label(self):
        return "value"

    def actions(self):
        return ()


def _ui_result(task: str = "dos"):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{task}.out",
        output_values={"value": _Value()},
    )


def test_result_provenance_keeps_file_version_but_not_atoms(tmp_path):
    potential = tmp_path / "Fe.pot"
    potential.write_text("first", encoding="utf-8")
    atoms = Atoms("Fe")
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        atoms,
        potential_path=str(potential),
    )

    record = store.add_result(
        _ui_result(),
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=atoms,
        input_parameters=None,
        directory=str(tmp_path),
    )

    state = store.state(state_id)
    assert not hasattr(state, "atoms")
    assert not hasattr(record, "atoms")
    assert record.input_potential == state.potential
    assert record.input_potential is not None
    assert record.input_potential.available
    assert record.input_potential.is_current()

    potential.write_text("a newer and longer version", encoding="utf-8")

    assert not record.input_potential.is_current()
    assert record.input_potential.current().path == potential.resolve()


def test_scf_records_output_potential_version(tmp_path):
    potential = tmp_path / "Fe.pot"
    potential.write_text("converged", encoding="utf-8")
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)

    record = store.add_result(
        _ui_result("scf"),
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=str(tmp_path),
        output_atoms=Atoms("Fe"),
        output_potential_path=str(potential),
    )

    assert record.output_state_id is not None
    assert record.output_potential == store.state(record.output_state_id).potential
    assert record.output_potential == PotentialFileVersion.capture(potential)


def test_changed_potential_offers_current_version_action(tmp_path):
    _application = QApplication.instance() or QApplication([])
    potential = tmp_path / "Fe.pot"
    potential.write_text("old", encoding="utf-8")
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"),
        potential_path=str(potential),
    )
    record = store.add_result(
        _ui_result(),
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=str(tmp_path),
    )
    potential.write_text("current version", encoding="utf-8")

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_workspace_state(structure_id, state_id)
    widget.set_results(store)
    item = widget._find_result_item(record.id)
    assert item is not None
    widget._selector.setCurrentItem(item)

    assert not widget._use_state_button.isHidden()
    assert widget._use_state_button.text() == (
        "Continue with current version of this potential"
    )
    widget.close()


def test_using_changed_potential_creates_fresh_state_from_current_file(
    monkeypatch,
    tmp_path,
):
    potential = tmp_path / "Fe.pot"
    potential.write_text("old", encoding="utf-8")
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), potential_path=str(potential))
    )
    old_structure_id = controller.structure_id
    old_state_id = controller.state_id
    record = controller.result_store.add_result(
        _ui_result(),
        structure_id=old_structure_id,
        input_state_id=old_state_id,
        atoms=controller.atoms,
        input_parameters=None,
        directory=str(tmp_path),
    )
    potential.write_text("current version", encoding="utf-8")
    current_atoms = Atoms("Ni")
    monkeypatch.setattr(
        controller_module.Potential,
        "from_file",
        lambda _path: SimpleNamespace(atoms=current_atoms),
    )

    controller.use_result_state(record.id)

    assert controller.atoms is current_atoms
    assert controller.potential_path == str(potential.resolve())
    assert controller.structure_id != old_structure_id
    assert controller.state_id != old_state_id
    assert controller.result is None
    active = controller.result_store.state(controller.state_id)
    assert active.potential == PotentialFileVersion.capture(potential)
