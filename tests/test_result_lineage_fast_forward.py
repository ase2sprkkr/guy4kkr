from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


def test_scf_does_not_fast_forward_across_use_for_new_calculation():
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), potential_path="P0.pot")
    )
    request = controller.create_calculation_request() if controller.input_parameters else None
    # Construct the launch snapshot explicitly because this test intentionally has
    # no real InputParameters object.
    from guy4ase.gui.application.workspace_controller import CalculationRequest

    request = CalculationRequest(
        atoms=controller.atoms,
        structure_provenance=controller.structure_provenance,
        input_parameters=object(),
        directory="run",
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )

    controller.use_for_new_calculation(
        expected_state_id=controller.state_id,
    )
    restart_state = controller.state_id
    assert restart_state != request.state_id
    assert controller.potential_path == str(Path("P0.pot").resolve())

    loaded = LoadedResult(
        result=SimpleNamespace(task_name="scf"),
        output_path=None,
        potential_path=Path("P1.pot"),
        atoms=Atoms("Fe"),
        potential_error=None,
        directory="run",
    )
    adoption = controller.adopt_calculation_result(loaded, request=request)

    assert not adoption.workspace_updated
    assert controller.state_id == restart_state
    assert controller.potential_path == str(Path("P0.pot").resolve())
    assert controller.restarted
    assert adoption.record.output_state_id != restart_state
