from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.structure_provenance import materialize_structure
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


def test_scf_does_not_fast_forward_across_use_for_new_calculation(tmp_path):
    first_potential = tmp_path / "P0.pot"
    first_potential.write_text("first")
    first_version = PotentialFileVersion.capture(first_potential)
    initial_structure = materialize_structure(
        Atoms("Fe"),
        potential_version=first_version,
    )
    controller = WorkspaceController(WorkspaceState(structure=initial_structure))
    assert controller.structure_provenance is not None
    assert controller.structure_id is not None
    assert controller.state_id is not None
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
    assert controller.potential_path == str(first_potential.resolve())

    second_potential = tmp_path / "P1.pot"
    second_potential.write_text("second")
    second_version = PotentialFileVersion.capture(second_potential)
    output_structure = materialize_structure(
        Atoms("Fe"),
        potential_version=second_version,
    )
    loaded = LoadedResult(
        result=SimpleNamespace(task_name="scf"),
        output_path=None,
        potential_path=second_potential.resolve(),
        potential_version=second_version,
        structure=output_structure,
        potential_error=None,
        directory="run",
    )
    adoption = controller.adopt_calculation_result(loaded, request=request)

    assert not adoption.workspace_updated
    assert controller.state_id == restart_state
    assert controller.potential_path == str(first_potential.resolve())
    assert controller.restarted
    assert adoption.record.output_state_id != restart_state
