from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application import workspace_controller as controller_module
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


def _result(task: str):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{task}.out",
        output_values={"value": _Value()},
    )


def _scf_versions(controller, potential, tmp_path):
    store = controller.result_store
    structure_id = controller.structure_id
    initial_state_id = controller.state_id
    assert structure_id is not None
    assert initial_state_id is not None

    potential.write_text("version one", encoding="utf-8")
    scf1 = store.add_result(
        _result("scf"),
        structure_id=structure_id,
        input_state_id=initial_state_id,
        atoms=controller.atoms,
        input_parameters=None,
        directory=str(tmp_path),
        output_atoms=Atoms("Fe"),
        output_potential_path=str(potential),
    )
    assert scf1.output_state_id is not None
    assert scf1.output_potential is not None

    potential.write_text("version two is deliberately longer", encoding="utf-8")
    scf2 = store.add_result(
        _result("scf"),
        structure_id=structure_id,
        input_state_id=scf1.output_state_id,
        atoms=controller.atoms,
        input_parameters=None,
        directory=str(tmp_path),
        output_atoms=Atoms("Fe"),
        output_potential_path=str(potential),
    )
    assert scf2.output_state_id is not None
    assert scf2.output_potential is not None
    return scf1, scf2


def test_continue_with_current_version_reuses_known_scf_state(monkeypatch, tmp_path):
    potential = tmp_path / "Fe.pot"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    scf1, scf2 = _scf_versions(controller, potential, tmp_path)
    store = controller.result_store
    structures_before = store.structures

    parsed_atoms = Atoms("Fe")
    parse_calls = []

    def parse_potential(_path):
        parse_calls.append(_path)
        return SimpleNamespace(atoms=parsed_atoms)

    monkeypatch.setattr(
        controller_module.Potential,
        "from_file",
        parse_potential,
    )

    controller.use_result_state(scf1.id, scf2.output_potential)

    assert controller.state_id == scf2.output_state_id
    assert controller.structure_id == store.state(scf2.output_state_id).structure_id
    assert controller.atoms is parsed_atoms
    assert store.structures == structures_before
    active = store.state(controller.state_id)
    assert active.potential_source_result_id == scf2.id
    assert store.potential_source_result(controller.state_id) is scf2
    assert len(parse_calls) == 1

    dos = store.add_result(
        _result("dos"),
        structure_id=controller.structure_id,
        input_state_id=controller.state_id,
        atoms=controller.atoms,
        input_parameters=None,
        directory=str(tmp_path),
    )
    assert dos.input_state_id == scf2.output_state_id
    assert store.potential_source_result(dos.input_state_id) is scf2

    generation = controller.generation
    controller.use_result_state(scf1.id, scf2.output_potential)

    assert controller.state_id == scf2.output_state_id
    assert controller.generation == generation
    assert store.structures == structures_before
    assert len(parse_calls) == 1


def test_current_version_action_hides_when_that_version_is_already_active(tmp_path):
    _application = QApplication.instance() or QApplication([])
    potential = tmp_path / "Fe.pot"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    scf1, scf2 = _scf_versions(controller, potential, tmp_path)
    store = controller.result_store

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_workspace_state(
        store.state(scf2.output_state_id).structure_id,
        scf2.output_state_id,
    )
    widget.set_results(store)
    old_item = widget._find_result_item(scf1.id)
    assert old_item is not None
    widget._selector.setCurrentItem(old_item)

    assert widget._use_state_button.isHidden()
    assert widget._use_state_potential_version is None
    widget.close()
