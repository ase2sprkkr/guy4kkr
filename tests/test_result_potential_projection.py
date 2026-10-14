from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_capture import (
    capture_result,
    capture_structure,
    resolve_potential_version,
)
from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.result_presentation import present_result_tree
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Value:
    info = ""

    def __init__(self, name: str):
        self.display_name = name

    def value_label(self) -> str:
        return self.display_name

    @staticmethod
    def actions() -> tuple[str, ...]:
        return ()


def _result(task: str, name: str):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{name}.out",
        output_values={"value": _Value(name)},
    )


def _capture(result, parameters=object(), *, output_path=None, potential_path=None):
    return capture_result(
        result,
        input_parameters=parameters,
        output_path=output_path,
        potential_path=potential_path,
    )


def _add_structure(history: ResultHistory, atoms=Atoms("Fe"), potential_path=None):
    return history.add_structure_state(
        capture_structure(atoms, potential_path=potential_path)
    )


def _widget() -> ResultActionsWidget:
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )


def _set_history(widget: ResultActionsWidget, history: ResultHistory) -> None:
    widget.set_model(
        present_result_tree(
            history,
            current_structure_id=None,
            current_state_id=None,
        )
    )


def test_empty_spheres_breaks_potential_source_provenance():
    history = ResultHistory()
    structure_id, root = _add_structure(history)
    scf_output = capture_structure(Atoms("Fe"), potential_path="Fe.pot")
    scf = history.add_result(
        _capture(_result("scf", "scf")),
        structure_id=structure_id,
        input_state_id=root,
        directory="run",
        output_structure_snapshot=scf_output.structure_snapshot,
        output_potential_path=scf_output.potential_path,
        output_potential_version=scf_output.potential_version,
    )
    scf_state = scf.output_state_id
    assert scf_state is not None
    assert history.potential_source_result(scf_state) is None

    empty_output = capture_structure(Atoms("FeX"), potential_path=None)
    empty_spheres = history.add_result(
        _capture(EmptySpheresResult(found=1), {}),
        structure_id=structure_id,
        input_state_id=scf_state,
        directory="run",
        output_structure_snapshot=empty_output.structure_snapshot,
        output_potential_path=None,
    )
    empty_state = empty_spheres.output_state_id
    assert empty_state is not None
    assert history.potential_source_result(empty_state) is None

    dos = history.add_result(
        _capture(_result("dos", "dos")),
        structure_id=structure_id,
        input_state_id=empty_state,
        directory="run",
    )

    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    _set_history(widget, history)
    structure = widget._selector.topLevelItem(0)
    labels = [structure.child(i).text(0).split(" — ", 1)[0] for i in range(3)]
    assert labels == ["SCF", "Empty spheres", "DOS"]
    assert structure.child(0).childCount() == 0
    assert widget._find_result_item(dos.id).parent() is structure
    widget.close()


def test_explicit_potential_replacement_does_not_inherit_old_source(tmp_path):
    first = tmp_path / "first.pot"
    first.write_text("first")
    external = tmp_path / "external.pot"
    external.write_text("external")

    history = ResultHistory()
    structure_id, root = _add_structure(history)
    scf_output = capture_structure(Atoms("Fe"), potential_path=first)
    scf = history.add_result(
        _capture(_result("scf", "scf")),
        structure_id=structure_id,
        input_state_id=root,
        directory="run",
        output_structure_snapshot=scf_output.structure_snapshot,
        output_potential_path=scf_output.potential_path,
        output_potential_version=scf_output.potential_version,
    )
    scf_state = scf.output_state_id
    assert scf_state is not None
    assert history.potential_source_result(scf_state) is scf

    replacement = history.add_child_state(
        scf_state,
        potential_path=str(external),
        potential_version=resolve_potential_version(external),
    )

    assert history.state(replacement).potential_path == str(external)
    assert history.potential_source_result(replacement) is None


def test_native_result_using_imported_scf_stays_under_import_directory(tmp_path):
    _application = QApplication.instance() or QApplication([])
    history = ResultHistory()
    directory = str(tmp_path / "imported")
    potential = Path(directory) / "Fe.pot"
    potential.parent.mkdir()
    potential.write_text("potential")
    structure = capture_structure(Atoms("Fe"), potential_path=potential)
    imported_scf = history.add_external_result(
        _capture(
            _result("scf", "imported"),
            output_path=Path(directory) / "scf.out",
            potential_path=potential,
        ),
        structure=structure,
        directory=directory,
        produces_state=True,
    )
    state_id = imported_scf.output_state_id
    assert state_id is not None
    assert imported_scf.imported
    assert history.potential_source_result(state_id) is imported_scf

    dos = history.add_result(
        _capture(_result("dos", "native")),
        structure_id=imported_scf.structure_id,
        input_state_id=state_id,
        directory="new-run",
    )

    widget = _widget()
    _set_history(widget, history)

    assert widget._selector.topLevelItemCount() == 1
    directory_item = widget._selector.topLevelItem(0)
    assert directory_item.text(0) == directory
    assert directory_item.childCount() == 1
    scf_item = directory_item.child(0)
    assert scf_item.text(0).startswith("SCF")
    assert scf_item.childCount() == 1
    assert scf_item.child(0).text(0).startswith("DOS")
    assert widget._find_result_item(dos.id).parent() is scf_item
    widget.close()


def test_hidden_import_only_structure_does_not_consume_formula_number(tmp_path):
    _application = QApplication.instance() or QApplication([])
    history = ResultHistory()
    directory = str(tmp_path / "imported")
    potential = Path(directory) / "Fe.pot"
    potential.parent.mkdir()
    potential.write_text("potential")
    structure = capture_structure(Atoms("Fe"), potential_path=potential)
    imported_scf = history.add_external_result(
        _capture(
            _result("scf", "imported"),
            output_path=Path(directory) / "scf.out",
            potential_path=potential,
        ),
        structure=structure,
        directory=directory,
        produces_state=True,
    )
    imported_state = imported_scf.output_state_id
    assert imported_state is not None
    history.add_result(
        _capture(_result("dos", "native-from-import")),
        structure_id=imported_scf.structure_id,
        input_state_id=imported_state,
        directory="new-run",
    )

    visible_structure, visible_state = _add_structure(history)
    history.add_result(
        _capture(_result("dos", "visible")),
        structure_id=visible_structure,
        input_state_id=visible_state,
        directory="visible-run",
    )

    widget = _widget()
    _set_history(widget, history)

    assert widget._selector.topLevelItemCount() == 2
    assert widget._selector.topLevelItem(0).text(0) == "Fe"
    assert widget._selector.topLevelItem(1).text(0) == directory
    widget.close()
