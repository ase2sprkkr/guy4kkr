from ase import Atoms
import pytest

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


def test_failed_in_place_edit_abandons_draft_and_restores_logical_structure():
    atoms = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    provenance = controller.structure_provenance
    state_id = controller.state_id

    def fail(candidate):
        assert candidate is atoms
        candidate.symbols = "Cu"
        candidate.cell[0, 0] = 9.0
        raise RuntimeError("edit failed")

    with pytest.raises(RuntimeError, match="edit failed"):
        controller.apply_structure_edit(fail, expected_provenance=provenance)

    # The checked-out runtime object was deliberately mutated in place and is
    # abandoned. The workspace rematerializes the unchanged logical state from
    # provenance instead of trying to roll arbitrary mutations back.
    restored = controller.atoms
    assert restored is not atoms
    assert restored.get_chemical_symbols() == ["Fe"]
    assert restored.cell[0, 0] == 1.0
    assert controller.structure_provenance is provenance
    assert controller.state_id == state_id
    assert controller.result_history.results == ()


def test_cancelled_in_place_edit_discards_mutated_draft():
    atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    provenance = controller.structure_provenance

    def cancel(candidate):
        candidate.symbols = "Cu"
        return None

    assert controller.apply_structure_edit(
        cancel,
        expected_provenance=provenance,
    ) is None

    assert controller.structure_provenance is provenance
    assert controller.atoms.get_chemical_symbols() == ["Fe"]
