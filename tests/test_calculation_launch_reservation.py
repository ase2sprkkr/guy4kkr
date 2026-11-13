from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def _controller(tmp_path):
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )


def test_run_flow_selects_profile_and_passes_it_to_window(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda parent: (True, "cluster"),
    )
    monkeypatch.setattr(
        calculation_flow,
        "profile_description",
        lambda name: f"profile:{name}",
    )

    parent = object()
    window = calculation_flow.run_calculation(
        controller,
        recent,
        parent,
    )

    assert window is not None
    assert captured["profile_name"] == "cluster"
    assert captured["profile_description"] == "profile:cluster"
    assert captured["parent"] is parent
    assert "run_registry" not in captured
    assert "launch_lock" not in captured


def test_cancelled_profile_selection_does_not_construct_window(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    constructed = []

    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda parent: (False, None),
    )
    monkeypatch.setattr(
        calculation_flow,
        "SprkkrRunWindow",
        lambda **kwargs: constructed.append(kwargs),
    )

    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
    ) is None
    assert constructed == []


def test_automatic_profile_is_distinct_from_cancel(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda parent: (True, None),
    )
    monkeypatch.setattr(
        calculation_flow,
        "profile_description",
        lambda name: "automatic",
    )

    assert calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
    ) is not None
    assert captured["profile_name"] is None
