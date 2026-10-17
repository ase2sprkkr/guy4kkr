from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr import InputParameters, TaskResult
from ase2sprkkr.execution import (
    ExecutionManager,
    ResultFilesRecord,
    RunState,
    RunStore,
)
from ase2sprkkr.outputs.reader_registry import reader_registry

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.flows import calculation as calculation_flow


def test_persistent_task_identity_round_trip_drives_recompute_editor(
    monkeypatch,
    tmp_path,
):
    """Keep requested/effective task semantics intact across both packages."""
    parameters = InputParameters.create("ARPES")
    parameters.TASK.TASK = "SPLEED"
    parameters.CONTROL.DATASET = "contract"

    input_path = tmp_path / "contract.inp"
    output_path = tmp_path / "contract.out"
    with input_path.open("w") as stream:
        parameters.save_to_file(stream, validate=False)
    output_path.write_text("synthetic persistent output\n")

    manager = ExecutionManager(RunStore(tmp_path / "runs"))
    run = manager.new_record(
        task="SPLEED",
        input_definition="ARPES",
        requested_task="ARPES",
        directory=tmp_path,
        result_files=ResultFilesRecord(
            input_file=str(input_path),
            output_file=str(output_path),
            input_files=(str(input_path),),
            output_files=(str(output_path),),
        ),
    )
    manager.store.save(run)
    run = manager.finalize(run, state=RunState.FINISHED, return_code=0)

    class Reader:
        def __init__(
            self,
            input_parameters,
            calculator,
            directory,
            task_name=None,
        ):
            self.input_parameters = input_parameters
            self.calculator = calculator
            self.directory = directory
            self.task_name = task_name

        def read_from_file(
            self,
            output_file,
            *,
            return_code,
            input_file=None,
            directory=None,
        ):
            result = TaskResult(
                self.input_parameters,
                self.calculator,
                directory or self.directory,
                output_file=output_file,
                input_file=input_file,
                task_name=self.task_name,
            )
            result.complete(None, return_code)
            return result

    resolved_tasks = []

    def reader_class_for_task(task):
        resolved_tasks.append(task)
        return Reader

    monkeypatch.setattr(reader_registry, "class_for_task", reader_class_for_task)

    source = PersistentJobSource(manager)
    loaded = source.load_result(run.id)

    assert len(resolved_tasks) == 1
    assert resolved_tasks[0].name == "SPLEED"
    assert resolved_tasks[0].input_parameters_definition_name == "ARPES"
    assert loaded.task_name.lower() == "spleed"
    assert loaded.input_parameters.task_name.upper() == "ARPES"
    assert loaded.input_parameters.task_definition.name.upper() == "SPLEED"
    assert loaded.run_record.task == "SPLEED"
    assert loaded.run_record.input_definition == "ARPES"
    assert loaded.run_record.requested_task == "ARPES"

    history = ResultStore()
    record = history.add_external_result(
        loaded,
        atoms=None,
        input_parameters=loaded.input_parameters,
        directory=str(tmp_path),
        output_path=output_path,
        potential_path=None,
        persistent_ref=run.id,
    )

    assert record.task_name == "spleed"
    assert record.input_parameters.task_name.upper() == "ARPES"
    assert record.input_parameters.task_definition.name.upper() == "SPLEED"

    edited = record.input_parameters.copy(copy_values=True)
    replacements = []

    def replace_input_parameters(
        value,
        *,
        expected_input_parameters_generation,
        expected_structure_generation,
    ):
        replacements.append(
            (
                value,
                expected_input_parameters_generation,
                expected_structure_generation,
            )
        )
        return object()

    controller = SimpleNamespace(
        result_store=history,
        directory=str(tmp_path),
        structure_generation=object(),
        input_parameters_generation=object(),
        atoms=Atoms("Fe"),
        replace_input_parameters=replace_input_parameters,
    )
    dialog_calls = []

    class GuidedDialog:
        class DialogCode:
            Accepted = object()

        def __init__(self, task, value, *, parent, atoms):
            dialog_calls.append((task, value, parent, atoms))

        def exec(self):
            return self.DialogCode.Accepted

        def parameters(self):
            return edited

    monkeypatch.setattr(calculation_flow, "GuidedInputParametersDialog", GuidedDialog)
    monkeypatch.setattr(
        calculation_flow,
        "edit_input_parameters",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("requested ARPES must use the Guided editor")
        ),
    )
    monkeypatch.setattr(
        calculation_flow,
        "document_change_applied",
        lambda parent, change: True,
    )
    launched = object()
    monkeypatch.setattr(
        calculation_flow,
        "run_calculation",
        lambda *_args, **_kwargs: launched,
    )

    result = calculation_flow.recompute_result(
        controller,
        object(),
        object(),
        record.id,
    )

    assert result is launched
    assert len(dialog_calls) == 1
    task, dialog_parameters, _parent, _atoms = dialog_calls[0]
    assert task.lower() == "arpes"
    assert dialog_parameters.task_name.upper() == "ARPES"
    assert dialog_parameters.task_definition.name.upper() == "SPLEED"
    assert replacements == [
        (
            edited,
            controller.input_parameters_generation,
            controller.structure_generation,
        )
    ]
