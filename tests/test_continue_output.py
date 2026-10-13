from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import files as file_flows
from guy4ase.main import GuiApplication


def _loaded_scf(path, *, atoms=None) -> LoadedResult:
    return LoadedResult(
        result=SimpleNamespace(task_name="scf", output_values={}),
        output_path=path,
        potential_path=None,
        atoms=atoms if atoms is not None else Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        potential_error=None,
        directory=str(path.parent),
        input_parameters=None,
    )


def _calculate_actions(window) -> list[str]:
    layout = window._action_group_layouts.get(window._GROUP_CALCULATE)
    if layout is None:
        return []
    return [
        str(
            layout.itemAt(index).widget().property("workflowActionTitle")
            or layout.itemAt(index).widget().text().splitlines()[0]
        )
        for index in range(1, layout.count())
    ]


def test_continue_output_activates_state_and_reuses_same_result(tmp_path, monkeypatch):
    output = tmp_path / "SCF.out"
    output.write_text("first calculation", encoding="utf-8")
    loaded = _loaded_scf(output)
    monkeypatch.setattr(file_flows, "_read_output", lambda _path, _parent: loaded)

    controller = WorkspaceController()
    recent = RecentFiles(tmp_path / "recent.json")

    assert file_flows.continue_output(controller, recent, output, None)
    assert len(controller.result_store.results) == 1
    record = controller.result_store.results[0]
    assert controller.state_id == record.output_state_id
    assert controller.atoms is not None
    assert controller.directory == str(tmp_path)
    assert controller.can_run_task("scf")

    generation = controller.generation
    assert file_flows.continue_output(controller, recent, output, None)
    assert len(controller.result_store.results) == 1
    assert controller.state_id == record.output_state_id
    assert controller.generation == generation


def test_restart_after_continue_keeps_scf_action_available(tmp_path, monkeypatch):
    output = tmp_path / "SCF.out"
    output.write_text("calculation", encoding="utf-8")
    loaded = _loaded_scf(output)
    monkeypatch.setattr(file_flows, "_read_output", lambda _path, _parent: loaded)

    controller = WorkspaceController()
    recent = RecentFiles(tmp_path / "recent.json")
    assert file_flows.continue_output(controller, recent, output, None)

    controller.use_for_new_calculation(expected_generation=controller.generation)

    assert controller.restarted
    assert controller.scf_status() == "START"
    assert controller.can_run_task("scf")


def test_workflow_shows_scf_action_after_continue_and_restart(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    output = tmp_path / "SCF.out"
    output.write_text("calculation", encoding="utf-8")
    loaded = _loaded_scf(output)
    monkeypatch.setattr(file_flows, "_read_output", lambda _path, _parent: loaded)

    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
    )
    window = gui.create_workflow_window()

    window._continue_recent("output", str(output))
    application.processEvents()
    assert "Converge SCF" in _calculate_actions(window)

    gui.controller.use_for_new_calculation(
        expected_generation=gui.controller.generation,
    )
    application.processEvents()
    assert "Converge SCF" in _calculate_actions(window)
    window.close()


def test_overwritten_output_path_creates_new_result(tmp_path):
    output = tmp_path / "SCF.out"
    output.write_text("first", encoding="utf-8")
    controller = WorkspaceController()

    first = controller.adopt_external_result(_loaded_scf(output)).record
    assert first is not None

    output.write_text("a different second calculation", encoding="utf-8")
    second = controller.adopt_external_result(_loaded_scf(output)).record

    assert second is not None
    assert second.id != first.id
    assert len(controller.result_store.results) == 2
