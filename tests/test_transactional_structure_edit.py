from ase import Atoms
import pytest

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


def test_failed_structure_edit_does_not_mutate_workspace():
    atoms = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    result = object()
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot", result=result)
    )
    generation = controller.generation

    def fail(candidate):
        candidate.symbols = "Cu"
        candidate.cell[0, 0] = 9.0
        raise RuntimeError("edit failed")

    with pytest.raises(RuntimeError, match="edit failed"):
        controller.apply_structure_edit(fail, expected_generation=generation)

    assert controller.workspace.atoms is atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert atoms.cell[0, 0] == 1.0
    assert controller.workspace.result is result
    assert controller.workspace.result_history == (result,)
    assert controller.workspace.potential_path == "Fe.pot"
    assert controller.generation == generation
