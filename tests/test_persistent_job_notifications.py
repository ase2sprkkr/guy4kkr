"""Tests for persistent-job change notification wiring."""
from __future__ import annotations

from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.main import GuiApplication


class _Parameters:
    task_name = "scf"

    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def test_run_flow_forwards_persistent_job_change_callback(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    callback = object()
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def width(self):
            return 100

        def height(self):
            return 100

        def move(self, _position):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _profile: None)

    calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
        persistent_job_changed=callback,
    )

    assert captured["persistent_job_changed"] is callback


def test_application_queues_job_reload_on_gui_thread(_qt_application, tmp_path):
    class Source:
        def __init__(self) -> None:
            self.changed = []

        def job_changed(self, job_id: str) -> None:
            self.changed.append(job_id)

    source = Source()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        project_repository=object(),
        persistent_jobs=source,
    )

    gui.persistentJobChanged.emit("run-17")

    assert source.changed == []
    _qt_application.processEvents()
    assert source.changed == ["run-17"]
