from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


def test_scf_fast_forwards_across_restart_marker_when_potential_is_unchanged():
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), potential_path="P0.pot")
    )
    request = CalculationRequest(
        atoms=controller.atoms,
        input_parameters=object(),
        directory="run",
        generation=controller.generation,
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )

    controller.use_for_new_calculation(
        expected_generation=controller.generation,
    )
    restart_state = controller.state_id
    assert restart_state != request.state_id
    assert controller.potential_path == "P0.pot"

    loaded = LoadedResult(
        result=SimpleNamespace(task_name="scf"),
        output_path=None,
        potential_path=Path("P1.pot"),
        atoms=Atoms("Fe"),
        potential_error=None,
        directory="run",
    )
    adoption = controller.adopt_calculation_result(loaded, request=request)

    assert adoption.workspace_updated
    assert controller.state_id == adoption.record.output_state_id
    assert controller.state_id != restart_state
    assert controller.potential_path == "P1.pot"
    assert not controller.restarted
