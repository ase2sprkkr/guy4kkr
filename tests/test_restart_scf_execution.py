from ase import Atoms

from guy4ase.gui.application.workspace import Generation
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs.run_calculation import _SprkkrRunWorker


def test_worker_forwards_restart_scf_to_create_run(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=Generation(),
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
