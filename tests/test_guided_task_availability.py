from __future__ import annotations

import pytest
from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs import guided_input as guided_input_module
from guy4ase.gui.dialogs.guided_input import GuidedTaskUnavailable
from guy4ase.gui.flows import calculation as calculation_flow


def _controller(tmp_path) -> WorkspaceController:
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            directory=str(tmp_path),
        )
    )


@pytest.mark.parametrize("error", (KeyError("SCF"), ImportError("missing backend module")))
def test_backend_task_materialization_errors_become_unavailable(
    monkeypatch, error
):
    def fail_create(_task):
        raise error

    monkeypatch.setattr(guided_input_module.InputParameters, "create", fail_create)

    with pytest.raises(GuidedTaskUnavailable) as raised:
        guided_input_module.select_guided_input_parameters(
            "scf",
            dataset_default_mode="auto",
        )

    assert raised.value.__cause__ is error


def test_backend_task_programming_error_propagates(monkeypatch):
    def fail_create(_task):
        raise RuntimeError("broken task definition")

    monkeypatch.setattr(guided_input_module.InputParameters, "create", fail_create)

    with pytest.raises(RuntimeError, match="broken task definition"):
        guided_input_module.select_guided_input_parameters(
            "scf",
            dataset_default_mode="auto",
        )


def test_expected_guided_task_unavailability_is_reported(monkeypatch, tmp_path):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    messages = []

    def unavailable(*_args, **_kwargs):
        raise GuidedTaskUnavailable("SCF backend task could not be loaded")

    monkeypatch.setattr(
        calculation_flow,
        "select_guided_input_parameters",
        unavailable,
    )
    monkeypatch.setattr(
        calculation_flow.QMessageBox,
        "critical",
        lambda parent, title, message: messages.append((title, message)),
    )

    result = calculation_flow.configure_and_run_task(
        controller,
        recent,
        object(),
        "scf",
        dataset_default_mode="auto",
    )

    assert result is None
    assert messages == [
        ("Task Unavailable", "SCF backend task could not be loaded")
    ]


def test_later_import_errors_are_not_misreported_as_task_unavailable(
    monkeypatch, tmp_path
):
    controller = _controller(tmp_path)
    recent = RecentFiles(tmp_path / "recent.json")
    parameters = object()

    monkeypatch.setattr(
        calculation_flow,
        "select_guided_input_parameters",
        lambda *args, **kwargs: parameters,
    )

    def fail_run(*_args, **_kwargs):
        raise ImportError("programming error after task setup")

    monkeypatch.setattr(calculation_flow, "run_calculation", fail_run)

    with pytest.raises(ImportError, match="programming error after task setup"):
        calculation_flow.configure_and_run_task(
            controller,
            recent,
            object(),
            "scf",
            dataset_default_mode="auto",
        )

    assert controller.input_parameters is parameters
