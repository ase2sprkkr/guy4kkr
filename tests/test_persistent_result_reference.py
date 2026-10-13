from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs import run_calculation as run_module


class _Parameters:
    task_name = "DOS"

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def _loaded(result, *, persistent_ref=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=None,
        atoms=None,
        potential_error=None,
        directory=None,
        input_parameters=_Parameters(),
        persistent_ref=persistent_ref,
    )


def test_calculation_result_records_persistent_reference(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    request = controller.create_calculation_request()

    adoption = controller.adopt_calculation_result(
        _loaded(SimpleNamespace(task_name="dos"), persistent_ref="ase-run-123"),
        request=request,
    )

    assert adoption.record is not None
    assert adoption.record.persistent_ref == "ase-run-123"


def test_external_persistent_result_keeps_reference():
    controller = WorkspaceController()

    adoption = controller.adopt_external_result(
        _loaded(SimpleNamespace(task_name="dos"), persistent_ref="ase-run-456")
    )

    assert adoption.record is not None
    assert adoption.record.persistent_ref == "ase-run-456"


def test_worker_passes_persistent_runner_id_to_loaded_result(monkeypatch, tmp_path):
    request = SimpleNamespace(
        atoms=None,
        input_parameters=_Parameters(),
        directory=str(tmp_path),
        restart_scf=False,
    )
    worker = run_module._SprkkrRunWorker(request)
    result = SimpleNamespace(task_name="dos")
    runner = SimpleNamespace(
        id="ase-run-789",
        reference=None,
        wait=lambda: result,
    )
    captured = {}

    monkeypatch.setattr(run_module, "SPRKKR", lambda: object())
    monkeypatch.setattr(worker, "_launch", lambda _calculator: runner)

    def load(value, **kwargs):
        captured["result"] = value
        captured.update(kwargs)
        return _loaded(value, persistent_ref=kwargs["persistent_ref"])

    monkeypatch.setattr(run_module, "load_result", load)

    worker.run()

    assert captured["result"] is result
    assert captured["fallback_directory"] == str(tmp_path)
    assert captured["persistent_ref"] == "ase-run-789"
