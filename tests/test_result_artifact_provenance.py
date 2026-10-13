from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QToolButton

from guy4ase.gui.application.result_artifacts import ArtifactState
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _FileValue:
    name = "dos"
    display_name = "Density of states (DOS)"
    info = "DOS data"

    def __init__(self, path: Path, context: str):
        self._path = path
        self._context = context

    def path(self) -> str:
        return str(self._path)

    def value_label(self) -> str:
        return "<dos file>"

    def actions(self):
        return ("data",)

    def data(self) -> str:
        return f"{self._context}:{self._path.read_text()}"


def _add_result(store: ResultStore, path: Path, context: str):
    if not store.structures:
        structure_id, state_id = store.new_structure_state(
            Atoms("Fe"), potential_path=None
        )
    else:
        structure_id = store.structures[0].id
        state_id = store.results[-1].input_state_id
        assert state_id is not None

    value = _FileValue(path, context)
    result = SimpleNamespace(
        task_name="dos",
        output_file=f"{context}.out",
        output_values={"dos": value},
    )
    record = store.add_result(
        result,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=str(path.parent),
    )
    return record, value


def _result_store(path: Path):
    store = ResultStore()
    record, value = _add_result(store, path, "old")
    return store, record, value


def test_result_store_remembers_file_version_after_overwrite(tmp_path):
    path = tmp_path / "Fe.dos"
    path.write_text("historical")
    _store, record, _value = _result_store(path)

    artifact = record.artifacts["dos"]
    assert artifact.path == path.resolve()
    assert artifact.state() is ArtifactState.CURRENT

    path.write_text("new current contents")
    assert artifact.state() is ArtifactState.OVERWRITTEN

    path.unlink()
    assert artifact.state() is ArtifactState.MISSING


def test_historical_result_uses_known_current_result_with_clear_warning(tmp_path):
    _application = QApplication.instance() or QApplication([])
    path = tmp_path / "Fe.dos"
    path.write_text("historical")
    store, old_record, old_value = _result_store(path)
    seen: list[str] = []

    widget = ResultActionsWidget(
        lambda value, action: seen.append(getattr(value, action)()),
        show_values_without_actions=True,
    )
    widget.set_results(store)
    assert widget._selected_result_id() == old_record.id
    assert widget._artifact_warning.isHidden()

    path.write_text("new current contents")
    new_record, new_value = _add_result(store, path, "new")
    assert new_record.artifacts["dos"].state() is ArtifactState.CURRENT
    assert store.current_value_for_artifact(old_record.artifacts["dos"]) is new_value
    assert new_value is not old_value

    widget.set_results(store)
    assert widget._selected_result_id() == old_record.id

    assert not widget._artifact_warning.isHidden()
    warning = widget._artifact_warning.text().lower()
    assert "historical result" in warning
    assert "current contents" in warning
    assert "not the original data" in warning

    name = widget._grid.itemAtPosition(0, 0).widget()
    assert "⚠" in name.text()
    assert "overwritten" in name.toolTip().lower()

    buttons = widget._grid.itemAtPosition(0, 1).widget()
    action_button = buttons.findChild(QToolButton)
    assert action_button is not None
    assert "current contents" in action_button.toolTip().lower()
    action_button.click()
    assert seen == ["new:new current contents"]
    widget.close()
