from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application import sprkkr_execution as execution_module
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    RunProvenance,
    WorkspaceController,
)


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def test_workspace_restart_is_recorded_from_result_provenance(tmp_path):
    parameters = _Parameters()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=parameters,
            directory=str(tmp_path),
            restarted=True,
        )
    )

    provenance = controller.create_run_provenance()
    assert provenance.restart_scf is True
    result = SimpleNamespace(
        task_name="DOS",
        produces_potential=False,
        provenance=provenance,
    )
    adoption = controller.adopt_calculation_result(
        LoadedResult(
            result=result,
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=str(tmp_path),
            input_parameters=parameters,
        )
    )

    assert adoption.record is not None
    assert adoption.record.restart_scf is True
    assert controller.restarted


def test_execution_forwards_restart_scf_and_detaches_inputs(monkeypatch, tmp_path):
    atoms = Atoms("Fe")
    parameters = _Parameters()
    provenance = RunProvenance(1, 1, restart_scf=True)
    execution = SprkkrExecution(
        atoms,
        parameters,
        str(tmp_path),
        provenance,
        _Cancellation(),
    )

    submitted = []
    seen = {}

    class Runner:
        reference = None
        id = "test-run"

        def submit(self):
            submitted.append(True)

        def wait(self):
            return object()

        def cancel(self):  # pragma: no cover - cancellation is not expected
            raise AssertionError("runner must not be cancelled")

    class Calculator:
        def create_run(self, **kwargs):
            seen.update(kwargs)
            return Runner()

    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(
        execution_module,
        "load_result",
        lambda _result, **_kwargs: object(),
    )

    execution.run()

    assert seen["restart_scf"] is True
    assert seen["provenance"] is provenance
    assert seen["atoms"] is execution.atoms
    assert seen["atoms"] is not atoms
    assert seen["input_parameters"] is execution.input_parameters
    assert seen["input_parameters"] is not parameters
    assert submitted == [True]
