from __future__ import annotations

from ase import Atoms

from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    StructureAccessGate,
)
from guy4ase.gui.dialogs import run_calculation as run_dialog


def test_gui_runs_use_distinct_result_files(monkeypatch, tmp_path):
    calls = []

    class Process:
        def run(self):
            return object()

    class Calculator:
        def calculate(self, **kwargs):
            calls.append(kwargs)
            return Process()

    monkeypatch.setattr(run_dialog, "SPRKKR", Calculator)
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        generation=0,
    )

    run_dialog._SprkkrRunWorker(request, StructureAccessGate()).run()
    run_dialog._SprkkrRunWorker(request, StructureAccessGate()).run()

    assert len(calls) == 2
    for key in ("input_file", "potential_file", "output_file"):
        assert calls[0][key] != calls[1][key]
        assert calls[0][key].startswith("%a_%T_")
