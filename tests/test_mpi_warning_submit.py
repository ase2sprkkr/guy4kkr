from __future__ import annotations

import warnings

from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs import run_calculation as run_module


def test_worker_forwards_mpi_warning_from_submit(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=object(),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=object(),
    )
    worker = run_module._SprkkrRunWorker(request)
    monkeypatch.setattr(
        worker,
        "_file_names",
        lambda: ("run.inp", "run.pot", "run.out"),
    )

    class Runner:
        def submit(self):
            warnings.warn(
                "No MPI launcher on remote host",
                run_module.MpiNotFoundWarning,
            )

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    seen = []
    worker.warning.connect(seen.append)

    assert worker._launch(Calculator()) is not None
    assert seen == ["No MPI launcher on remote host"]
