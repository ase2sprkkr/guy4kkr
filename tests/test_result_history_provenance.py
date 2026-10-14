from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from ase import Atoms

from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


def _atoms() -> Atoms:
    atoms = Atoms("FeNi", positions=((0, 0, 0), (1, 1, 1)), cell=(3, 3, 3), pbc=True)
    atoms.set_array("spacegroup_kinds", np.asarray((0, 1), dtype=int))
    atoms.set_array("labels", np.asarray(("a", "b"), dtype=object))
    atoms.info["occupancy"] = {
        "0": {"Fe": 0.75, "Co": 0.25},
        "1": {"Ni": 1.0},
    }
    return atoms


def test_state_without_usable_potential_keeps_lightweight_structure_snapshot():
    atoms = _atoms()
    atoms.potential = object()
    history = ResultHistory()

    _, state_id = history.add_structure_state(capture_structure(atoms))
    state = history.state(state_id)

    assert state.structure_snapshot is not None

    atoms.positions[:] = 9
    atoms.info["occupancy"]["0"]["Fe"] = 0.0
    restored = state.structure_snapshot.to_atoms()

    assert np.allclose(restored.positions, ((0, 0, 0), (1, 1, 1)))
    assert restored.arrays["spacegroup_kinds"].tolist() == [0, 1]
    assert restored.arrays["labels"].tolist() == ["a", "b"]
    assert restored.info["occupancy"]["0"] == {"Fe": 0.75, "Co": 0.25}
    assert not hasattr(restored, "potential")


def test_state_with_usable_potential_uses_exact_version_as_structure_authority(tmp_path):
    potential = tmp_path / "Fe.pot"
    potential.write_text("potential", encoding="utf-8")
    version = PotentialFileVersion.capture(potential)
    history = ResultHistory()

    _, state_id = history.add_structure_state(
        capture_structure(_atoms(), potential_version=version)
    )
    state = history.state(state_id)

    assert state.potential_version is version
    assert state.potential_version.available
    assert state.potential_path == potential.resolve()
    assert state.structure_snapshot is None


def test_result_payload_is_not_used_as_mutable_provenance():
    history = ResultHistory()
    structure_id, state_id = history.add_structure_state(capture_structure(Atoms("Fe")))
    result = SimpleNamespace(task_name="dos", output_values={})
    captured = capture_result(
        result,
        input_parameters={"mesh": [10, 10, 10]},
        output_path=None,
        potential_path=None,
    )
    record = history.add_result(
        captured,
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )

    result.task_name = "scf"

    assert record.result is result
    assert record.task_name == "dos"
    assert record.input_parameters == {"mesh": [10, 10, 10]}


def test_historical_snapshot_restores_without_retaining_live_atoms():
    original = _atoms()
    controller = WorkspaceController(WorkspaceState(atoms=original))
    structure_id = controller.structure_id
    state_id = controller.state_id
    assert structure_id is not None
    assert state_id is not None

    record = controller.result_history.add_result(
        capture_result(
            SimpleNamespace(task_name="dos", output_values={}),
            input_parameters={},
            output_path=None,
            potential_path=None,
        ),
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )
    controller.replace_structure(Atoms("Cu"))

    controller.use_result_state(record.id)

    assert controller.atoms is not original
    assert controller.atoms.get_chemical_symbols() == ["Fe", "Ni"]
    assert controller.atoms.info["occupancy"]["0"] == {"Fe": 0.75, "Co": 0.25}
