from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.flows import calculation as calculation_flow


def test_non_guided_result_recompute_uses_expert_editor(monkeypatch):
    historical = InputParameters.create("TORQUE")
    edited = historical.copy(copy_values=True)
    record = SimpleNamespace(
        task_name="torque",
        input_parameters=historical,
    )
    replacements = []
    controller = SimpleNamespace(
        result_store=SimpleNamespace(result=lambda result_id: record),
        directory="calculation",
        generation=object(),
        atoms=Atoms("Fe"),
        replace_input_parameters=lambda parameters, *, expected_generation: (
            replacements.append((parameters, expected_generation)) or object()
        ),
    )
    editor_calls = []

    def edit(parameters, *, parent, atoms):
        editor_calls.append((parameters, parent, atoms))
        return edited

    monkeypatch.setattr(calculation_flow, "edit_input_parameters", edit)
    monkeypatch.setattr(
        calculation_flow,
        "document_change_applied",
        lambda parent, change: True,
    )
    launched = object()
    launch_calls = []

    def run(controller_arg, recent_files, parent, **kwargs):
        launch_calls.append((controller_arg, recent_files, parent, kwargs))
        return launched

    monkeypatch.setattr(calculation_flow, "run_calculation", run)
    parent = object()
    recent_files = object()

    result = calculation_flow.recompute_result(
        controller,
        recent_files,
        parent,
        17,
    )

    assert result is launched
    assert len(editor_calls) == 1
    editor_parameters, editor_parent, editor_atoms = editor_calls[0]
    assert editor_parameters is not historical
    assert editor_parameters.task_name.lower() == "torque"
    assert editor_parent is parent
    assert editor_atoms is controller.atoms
    assert replacements == [(edited, controller.generation)]
    assert launch_calls == [(
        controller,
        recent_files,
        parent,
        {"position_like_window": "expert-input", "persistent_job_changed": None},
    )]
