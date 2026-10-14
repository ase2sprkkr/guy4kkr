from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_history import ResultHistory


def test_empty_spheres_result_has_stable_task_identity():
    history = ResultHistory()
    structure_id, state_id = history.add_structure_state(
        capture_structure(Atoms("Fe"), potential_path=None)
    )
    captured = capture_result(
        EmptySpheresResult(found=2),
        input_parameters={},
        output_path=None,
        potential_path=None,
    )

    record = history.add_result(
        captured,
        structure_id=structure_id,
        input_state_id=state_id,
        directory=None,
    )

    assert record.task_name == "empty_spheres"
