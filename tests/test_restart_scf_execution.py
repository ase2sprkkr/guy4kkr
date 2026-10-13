from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import Generation, WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)
from guy4ase.gui.dialogs.run_calculation import _SprkkrRunWorker


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def test_workspace_restart_is_snapshotted_into_request_and_result(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            restarted=True,
        )
    )

    request = controller.create_calculation_request()
    assert request.restart_scf is True

    adoption = controller.adopt_calculation_result(
        LoadedResult(
            result=SimpleNamespace(task_name="DOS"),
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=str(tmp_path),
        ),
        request=request,
    )

    assert adoption.record is not None
    assert adoption.record.restart_scf is True
    assert controller.restarted


def test_worker_forwards_restart_scf_to_create_run(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=Generation(),
        structure_id=1,
        state_id=1,
        restart_scf=True,
    )
    worker = _SprkkrRunWorker(request)
    monkeypatch.setattr(
        worker,
        "_file_names",
        lambda: ("Fe.inp", "Fe.pot", "Fe.out"),
    )

    submitted = []
    seen = {}

    class Runner:
        def submit(self):
            submitted.append(True)

        def cancel(self):  # pragma: no cover - cancellation is not expected
            raise AssertionError("runner must not be cancelled")

    class Calculator:
        def create_run(self, **kwargs):
            seen.update(kwargs)
            return Runner()

    runner = worker._launch(Calculator())

    assert runner is not None
    assert seen["restart_scf"] is True
    assert seen["atoms"] is request.atoms
    assert seen["input_parameters"] is request.input_parameters
    assert submitted == [True]
