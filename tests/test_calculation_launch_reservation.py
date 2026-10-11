from ase import Atoms

from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def test_run_is_reserved_before_window_construction(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    recent = RecentFiles(tmp_path / "recent.json")
    active_runs = ActiveRunRegistry()
    callbacks = {}

    class Window:
        def __init__(self, **kwargs):
            assert active_runs.count == 1
            assert kwargs.get("on_activity_started") is None
            callbacks["ended"] = kwargs["on_activity_ended"]

        def show(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)

    window = calculation_flow.run_calculation(
        controller,
        recent,
        active_runs,
        parent=object(),
    )

    assert window is not None
    assert active_runs.count == 1

    callbacks["ended"](object())
    assert active_runs.count == 0


def test_failed_window_construction_releases_launch_reservation(
    monkeypatch, tmp_path
):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    active_runs = ActiveRunRegistry()

    class Window:
        def __init__(self, **_kwargs):
            assert active_runs.count == 1
            raise RuntimeError("window failed")

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)

    try:
        calculation_flow.run_calculation(
            controller,
            RecentFiles(tmp_path / "recent.json"),
            active_runs,
            parent=object(),
        )
    except RuntimeError as exc:
        assert str(exc) == "window failed"
    else:
        raise AssertionError("window construction error must propagate")

    assert active_runs.count == 0
