from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    RunProvenance,
    WorkspaceController,
)


def test_scf_does_not_fast_forward_across_use_for_new_calculation():
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), potential_path="P0.pot")
    )
    provenance = RunProvenance(
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )

    controller.use_for_new_calculation(
        expected_generation=controller.generation,
    )
    restart_state = controller.state_id
    assert restart_state != provenance.state_id
    assert controller.potential_path == "P0.pot"

    result = SimpleNamespace(
        task_name="scf",
        produces_potential=True,
        provenance=provenance,
    )
    loaded = LoadedResult(
        result=result,
        output_path=None,
        potential_path=Path("P1.pot"),
        atoms=Atoms("Fe"),
        potential_error=None,
        directory="run",
    )
    adoption = controller.adopt_calculation_result(loaded)

    assert not adoption.workspace_updated
    assert controller.state_id == restart_state
    assert controller.potential_path == "P0.pot"
    assert controller.restarted
    assert adoption.record.output_state_id != restart_state
