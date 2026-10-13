from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_store import ResultStore


def test_empty_spheres_result_has_stable_task_identity():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)

    record = store.add_result(
        EmptySpheresResult(found=2),
        structure_id=structure_id,
        input_state_id=state_id,
        atoms=Atoms("Fe"),
        input_parameters={},
        directory=None,
    )

    assert record.task_name == "empty_spheres"
