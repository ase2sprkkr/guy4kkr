from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


class _Parameters:
    task_name = "DOS"

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def _loaded(result, *, persistent_ref=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=None,
        atoms=None,
        potential_error=None,
        directory=None,
        input_parameters=_Parameters(),
        persistent_ref=persistent_ref,
    )


def test_calculation_result_records_persistent_reference(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    request = controller.create_calculation_request()

    adoption = controller.adopt_calculation_result(
        _loaded(SimpleNamespace(task_name="dos"), persistent_ref="ase-run-123"),
        request=request,
    )

    assert adoption.record is not None
    assert adoption.record.persistent_ref == "ase-run-123"


def test_external_persistent_result_keeps_reference():
    controller = WorkspaceController()

    adoption = controller.adopt_external_result(
        _loaded(SimpleNamespace(task_name="dos"), persistent_ref="ase-run-456")
    )

    assert adoption.record is not None
    assert adoption.record.persistent_ref == "ase-run-456"
